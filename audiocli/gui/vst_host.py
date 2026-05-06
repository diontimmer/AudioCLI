"""Helper-process VST/AU editor host for the optional desktop GUI.

This module is intentionally Qt-free.  The GUI launches it with
``python -m audiocli.gui.vst_host`` so Pedalboard's blocking native editor can
own this process' main thread while AudioCLI's main Qt event loop keeps moving.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any, TextIO

from audiocli.errors import OpError
from audiocli.vst_params import (
    apply_serialized_params as apply_initial_params,
)
from audiocli.vst_params import (
    first_attr as _first_attr,
)
from audiocli.vst_params import (
    normalize_param_entries,
    serialize_parameter_snapshot,
)

__all__ = [
    "apply_initial_params",
    "normalize_param_entries",
    "run_host",
    "serialize_parameter_snapshot",
]

POLL_INTERVAL_SECONDS = 0.25


def run_host(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    """Run one JSONL ``open`` command and host the plugin editor."""

    emitter = _JsonLineEmitter(stdout)
    try:
        command = _read_open_command(stdin)
    except Exception as exc:
        emitter.emit("error", stage="open", message=str(exc))
        return 2

    plugin_path = Path(str(command.get("plugin_path") or "")).expanduser()
    if not plugin_path.exists():
        emitter.emit("error", stage="load", message=f"Plugin path does not exist: {plugin_path}")
        return 2

    try:
        from pedalboard import load_plugin  # noqa: PLC0415

        plugin = load_plugin(str(plugin_path))
        apply_initial_params(plugin, command.get("params") or [])
    except Exception as exc:
        emitter.emit("error", stage="load", message=str(exc))
        return 2

    emitter.emit("loaded", plugin_path=str(plugin_path), display_name=_plugin_display_name(plugin))
    emitter.emit("parameters", parameters=serialize_parameter_snapshot(plugin))

    if not hasattr(plugin, "show_editor"):
        emitter.emit(
            "error",
            stage="editor",
            message="This plugin does not expose a native Pedalboard editor.",
        )
        emitter.emit("closed")
        return 2

    close_event = threading.Event()
    poll_stop = threading.Event()
    poller = threading.Thread(
        target=_poll_parameters,
        args=(plugin, emitter, poll_stop),
        name="audiocli-vst-parameter-poller",
        daemon=True,
    )
    poller.start()

    exit_code = 0
    try:
        plugin.show_editor(close_event)
    except Exception as exc:
        exit_code = 2
        emitter.emit("error", stage="editor", message=str(exc))
    finally:
        poll_stop.set()
        poller.join(timeout=1.0)
        emitter.emit("parameters", parameters=serialize_parameter_snapshot(plugin))
        emitter.emit("closed")

    return exit_code


def _read_open_command(stdin: TextIO) -> dict[str, Any]:
    line = stdin.readline()
    if not line:
        raise ValueError("Missing open command.")
    payload = json.loads(line)
    if not isinstance(payload, dict) or payload.get("type") != "open":
        raise ValueError("Expected an open command.")
    return payload


def _poll_parameters(plugin: Any, emitter: _JsonLineEmitter, stop_event: threading.Event) -> None:
    previous = ""
    while not stop_event.wait(POLL_INTERVAL_SECONDS):
        try:
            snapshot = serialize_parameter_snapshot(plugin)
            encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
        except Exception as exc:
            emitter.emit("error", stage="poll", message=str(exc))
            return
        if encoded != previous:
            previous = encoded
            emitter.emit("parameters", parameters=snapshot)


def _plugin_display_name(plugin: Any) -> str:
    value = _first_attr(plugin, ("name", "display_name", "plugin_name"))
    return str(value or type(plugin).__name__)


class _JsonLineEmitter:
    def __init__(self, stdout: TextIO) -> None:
        self._stdout = stdout
        self._lock = threading.Lock()

    def emit(self, event_type: str, **payload: Any) -> None:
        message = {"type": event_type, **payload}
        with self._lock:
            self._stdout.write(json.dumps(message, allow_nan=False, separators=(",", ":")) + "\n")
            self._stdout.flush()


def main() -> int:
    try:
        return run_host()
    except OpError as exc:
        sys.stdout.write(
            json.dumps({"type": "error", "stage": "params", "message": str(exc)}) + "\n"
        )
        sys.stdout.flush()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
