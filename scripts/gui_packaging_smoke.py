#!/usr/bin/env python3
"""Cross-platform smoke helper for AudioCLI GUI packaging candidates.

Static mode is safe in CI and must not import PySide6. Native GUI construction
is opt-in because CI images may not have a display server or Qt platform setup.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

LIVE_PLUGIN_ENV = "AUDIOCLI_TEST_VST_PATH"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--static",
        action="store_true",
        help="Run import/capability/plugin-directory checks only; never imports PySide6.",
    )
    parser.add_argument(
        "--construct-window",
        action="store_true",
        help="Construct the PySide6 main window in offscreen mode, then exit.",
    )
    parser.add_argument(
        "--entrypoint",
        help="Optional packaged CLI executable to invoke with --packaged-static-smoke.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    return parser


def run_static_smoke() -> dict[str, Any]:
    from audiocli.capabilities import list_capabilities
    from audiocli.plugin_discovery import (
        default_plugin_scan_directories,
        default_plugin_scan_directory_specs,
        discover_default_plugins,
    )

    capabilities = list_capabilities()
    capability_ids = [cap.id for cap in capabilities]
    default_scan_specs = default_plugin_scan_directory_specs()
    scan_dirs = default_plugin_scan_directories(existing_only=False)
    discovered_plugins = discover_default_plugins()
    live_plugin = os.environ.get(LIVE_PLUGIN_ENV)

    return {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "machine": platform.machine(),
        "capability_count": len(capabilities),
        "has_vst_capability": "builtin.external_plugin.vst" in capability_ids,
        "default_plugin_scan_specs": default_scan_specs,
        "resolved_plugin_scan_directories": [d.to_view_model() for d in scan_dirs],
        "discovered_plugins": [p.to_view_model() for p in discovered_plugins],
        "live_plugin_env": LIVE_PLUGIN_ENV,
        "live_plugin_status": "configured" if live_plugin else "skipped_missing_env",
        "live_plugin_path": live_plugin,
    }


def construct_window_smoke() -> dict[str, Any]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from audiocli.gui.app import create_main_window

    window = create_main_window(test_safe=True)
    return {
        "constructed_main_window": True,
        "window_class": type(window).__name__,
    }


def run_entrypoint_smoke(entrypoint: str) -> dict[str, Any]:
    command = [entrypoint, "--packaged-static-smoke"]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    return {
        "entrypoint": entrypoint,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    result: dict[str, Any] = {"static": run_static_smoke()}

    if args.construct_window:
        result["window"] = construct_window_smoke()

    if args.entrypoint:
        entrypoint = Path(args.entrypoint)
        if not entrypoint.exists():
            parser.error(f"entrypoint does not exist: {entrypoint}")
        result["entrypoint"] = run_entrypoint_smoke(str(entrypoint))

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        static = result["static"]
        print("AudioCLI GUI packaging smoke")
        print(f"python: {static['python']}")
        print(f"platform: {static['platform']} {static['machine']}")
        print(f"capabilities: {static['capability_count']}")
        print(f"vst capability: {static['has_vst_capability']}")
        print("plugin scan dirs:")
        for spec in static["default_plugin_scan_specs"]:
            print(f"- {spec['platform']} {spec['format']} {spec['scope']}: {spec['path']}")
        print(f"discovered plugins: {len(static['discovered_plugins'])}")
        print(f"live plugin: {static['live_plugin_status']}")
        if "window" in result:
            print(f"main window: {result['window']['window_class']}")
        if "entrypoint" in result:
            print(f"entrypoint returncode: {result['entrypoint']['returncode']}")

    failures: list[str] = []
    if not result["static"]["has_vst_capability"]:
        failures.append("missing builtin.external_plugin.vst capability")
    if "entrypoint" in result and result["entrypoint"]["returncode"] != 0:
        failures.append("packaged entrypoint smoke failed")

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
