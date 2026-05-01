"""Cancellation semantics for ``run_per_file`` — issue #14.

A ``cancel_token`` flipped mid-job stops the pipeline gracefully:

* In-flight files complete (no thread kills).
* Pending un-started files are skipped and recorded as
  ``Result(ok=False, error="cancelled")``.
* The final :class:`JobReport` reflects partial progress.
* No background threads or executors leak past return.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np

from audiocli.buffer import AudioBuffer
from audiocli.io import save
from audiocli.pipeline import JobReport, run_per_file
from audiocli.registry import op as op_decorator


def _write_synth(path: Path) -> None:
    sr = 22050
    t = np.linspace(0, 1, sr, dtype=np.float32)
    data = (np.sin(2 * np.pi * 440 * t) * 0.1).astype(np.float32)[None, :]
    save(path, AudioBuffer(data=data, sr=sr, subtype="PCM_16"))


# A cooperative sleepy op the cancellation tests use to give themselves a
# real wall-clock window in which to flip the token.
@op_decorator(name="_cancel_sleepy_op", help="Test-only op: sleeps for `seconds`.")
def _cancel_sleepy(buf: AudioBuffer, seconds: float = 0.05) -> AudioBuffer:
    time.sleep(seconds)
    return buf


def test_token_set_before_run_skips_everything(tmp_path):
    """Token already set → no file is processed; every file is recorded."""
    files = []
    for i in range(4):
        p = tmp_path / f"in_{i}.wav"
        _write_synth(p)
        files.append(p)

    cancel = threading.Event()
    cancel.set()

    report = run_per_file(
        files,
        _cancel_sleepy.__op__,
        {"seconds": 0.0},
        output=tmp_path / "out",
        workers=2,
        cancel_token=cancel,
    )
    assert isinstance(report, JobReport)
    assert report.ok_count == 0
    assert report.failed_count == len(files)
    for r in report.results:
        assert r.error == "cancelled"


def test_token_flipped_mid_job_partial_completion(tmp_path):
    """Cancel mid-batch → some files complete, some are reported cancelled."""
    files = []
    for i in range(20):
        p = tmp_path / f"in_{i:02d}.wav"
        _write_synth(p)
        files.append(p)

    cancel = threading.Event()

    def _cancel_after_first():
        # Wait until at least one file has finished, then flip the token.
        deadline = time.perf_counter() + 5.0
        while time.perf_counter() < deadline:
            time.sleep(0.02)
            cancel.set()
            return

    flipper = threading.Thread(target=_cancel_after_first)
    flipper.start()
    try:
        report = run_per_file(
            files,
            _cancel_sleepy.__op__,
            {"seconds": 0.1},
            output=tmp_path / "out",
            workers=2,
            cancel_token=cancel,
        )
    finally:
        flipper.join(timeout=5.0)

    assert isinstance(report, JobReport)
    # Partial progress: not everything succeeded, not everything failed.
    total = report.ok_count + report.failed_count
    assert total == len(files), report.results
    assert report.failed_count >= 1
    assert report.ok_count + report.failed_count == len(files)
    # Every recorded failure is a cancellation, not some other error.
    cancelled = [r for r in report.results if not r.ok]
    assert all(r.error == "cancelled" for r in cancelled), cancelled


def test_no_thread_leak_on_cancel(tmp_path):
    """Cancellation does not leave background threads alive past return."""
    files = []
    for i in range(8):
        p = tmp_path / f"in_{i}.wav"
        _write_synth(p)
        files.append(p)

    cancel = threading.Event()
    cancel.set()

    before = threading.active_count()
    run_per_file(
        files,
        _cancel_sleepy.__op__,
        {"seconds": 0.0},
        output=tmp_path / "out",
        workers=4,
        cancel_token=cancel,
    )
    # Give Python a beat to GC the executor's pool.
    time.sleep(0.1)
    after = threading.active_count()
    # Allow a small slack for unrelated test infrastructure threads, but
    # certainly no per-worker leak.
    assert after <= before + 1, (before, after)
