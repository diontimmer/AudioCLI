"""Qt process controller for the AudioCLI VST/AU editor helper."""

from __future__ import annotations

import json
import sys
from typing import Any

from PySide6.QtCore import QObject, QProcess, Signal


class VstHostController(QObject):
    """Launch and parse the JSONL VST editor helper process."""

    loaded = Signal(dict)
    parameters = Signal(list)
    closed = Signal(dict)
    error = Signal(str)
    status = Signal(str)
    exited = Signal(dict)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: QProcess | None = None
        self._stdout_buffer = ""
        self._stderr_buffer = ""
        self._starting_command: dict[str, Any] | None = None
        self._reported_error = False
        self._reported_closed = False

    def open_editor(self, *, plugin_path: str, params: list[str]) -> None:
        self.stop()
        process = QProcess(self)
        process.setProgram(sys.executable)
        process.setArguments(["-m", "audiocli.gui.vst_host"])
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.started.connect(self._send_open_command)
        process.readyReadStandardOutput.connect(self._read_stdout)
        process.readyReadStandardError.connect(self._read_stderr)
        process.errorOccurred.connect(self._on_process_error)
        process.finished.connect(self._on_process_finished)
        self._process = process
        self._stdout_buffer = ""
        self._stderr_buffer = ""
        self._reported_error = False
        self._reported_closed = False
        self._starting_command = {
            "type": "open",
            "plugin_path": plugin_path,
            "params": list(params),
        }
        self.status.emit("Opening editor...")
        process.start()

    def stop(self) -> None:
        process = self._process
        if process is None:
            return
        if process.state() != QProcess.ProcessState.NotRunning:
            process.terminate()
            if not process.waitForFinished(750):
                process.kill()
                process.waitForFinished(750)
        process.deleteLater()
        self._process = None
        self._starting_command = None

    def _send_open_command(self) -> None:
        process = self._process
        command = self._starting_command
        if process is None or command is None:
            return
        payload = json.dumps(command, separators=(",", ":")) + "\n"
        process.write(payload.encode("utf-8"))
        process.closeWriteChannel()

    def _read_stdout(self) -> None:
        process = self._process
        if process is None:
            return
        self._stdout_buffer += bytes(process.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        while "\n" in self._stdout_buffer:
            line, self._stdout_buffer = self._stdout_buffer.split("\n", 1)
            self._handle_line(line.strip())

    def _read_stderr(self) -> None:
        process = self._process
        if process is None:
            return
        self._stderr_buffer += bytes(process.readAllStandardError()).decode(
            "utf-8", errors="replace"
        )

    def _handle_line(self, line: str) -> None:
        if not line:
            return
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            self.error.emit(f"Host sent malformed output: {line[:160]}")
            return
        if not isinstance(payload, dict):
            return
        event_type = str(payload.get("type") or "")
        if event_type == "loaded":
            self.status.emit("Editor loaded.")
            self.loaded.emit(payload)
        elif event_type == "parameters":
            parameters = payload.get("parameters") or []
            if isinstance(parameters, list):
                self.parameters.emit(parameters)
        elif event_type == "closed":
            self._reported_closed = True
            self.status.emit("Editor closed.")
            self.closed.emit(payload)
        elif event_type == "error":
            message = str(payload.get("message") or "VST host error.")
            self._reported_error = True
            self.status.emit(message)
            self.error.emit(message)

    def _on_process_error(self, error: QProcess.ProcessError) -> None:
        self.error.emit(f"VST host failed to start or communicate: {error.name}")

    def _on_process_finished(
        self,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
    ) -> None:
        if self._stdout_buffer.strip():
            self._handle_line(self._stdout_buffer.strip())
            self._stdout_buffer = ""
        abnormal = exit_status != QProcess.ExitStatus.NormalExit or exit_code != 0
        if abnormal and not self._reported_error:
            detail = self._stderr_buffer.strip()
            message = f"VST host exited with code {exit_code}."
            if detail:
                message = f"{message} {detail[-240:]}"
            self.error.emit(message)
        elif not abnormal and not self._reported_closed:
            self._reported_closed = True
            self.status.emit("Editor closed.")
            self.closed.emit({"type": "closed", "source": "process"})
        self.exited.emit(
            {
                "exit_code": exit_code,
                "normal": not abnormal,
                "reported_error": self._reported_error,
                "reported_closed": self._reported_closed,
            }
        )
        self._process = None
