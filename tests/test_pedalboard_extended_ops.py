"""Extended first-party Pedalboard op coverage."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import numpy as np

from audiocli import list_ops
from audiocli.buffer import AudioBuffer
from audiocli.capabilities import list_capabilities, validate_capability_params
from audiocli.io import save


def _tone(*, sr: int = 44100, seconds: float = 0.1) -> AudioBuffer:
    t = np.arange(int(sr * seconds), dtype=np.float32) / sr
    data = (np.sin(2 * np.pi * 440 * t) * 0.25).astype(np.float32)[None, :]
    return AudioBuffer(data=data, sr=sr, subtype="PCM_16")


def _assert_audio_buffer(result: AudioBuffer, source: AudioBuffer) -> None:
    assert isinstance(result, AudioBuffer)
    assert result.sr == source.sr
    assert result.data.shape == source.data.shape
    assert result.data.dtype == np.float32
    assert np.isfinite(result.data).all()


def test_extended_pedalboard_ops_are_registered_and_exposed_as_capabilities() -> None:
    expected = {
        "clip",
        "convolve",
        "gsm",
        "highshelf",
        "ladder",
        "lowshelf",
        "mp3",
        "noisegate",
        "peak",
    }

    op_names = {info.name for info in list_ops(include_plugins=False)}
    capability_names = {cap.operation_name for cap in list_capabilities()}

    assert expected <= op_names
    assert expected <= capability_names


def test_extended_pedalboard_ops_process_audio(tmp_path: Path) -> None:
    source = _tone()
    impulse = AudioBuffer(
        data=np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32),
        sr=source.sr,
        subtype="PCM_16",
    )
    impulse_path = tmp_path / "impulse.wav"
    save(impulse_path, impulse)

    cases = [
        ("clip", {"threshold_db": -12.0}),
        ("convolve", {"impulse_response": str(impulse_path), "mix": 0.5}),
        ("gsm", {"quality": "Linear"}),
        ("highshelf", {"hz": 1200.0, "gain_db": 3.0, "q": 0.70710678}),
        ("ladder", {"mode": "LPF24", "cutoff_hz": 1000.0, "resonance": 0.2, "drive": 1.0}),
        ("lowshelf", {"hz": 180.0, "gain_db": -3.0, "q": 0.70710678}),
        ("mp3", {"vbr_quality": 7.0}),
        ("noisegate", {"threshold_db": -80.0, "ratio": 8.0, "attack_ms": 1.0, "release_ms": 50.0}),
        ("peak", {"hz": 700.0, "gain_db": 2.0, "q": 0.8}),
    ]

    for module_name, kwargs in cases:
        fn = getattr(import_module(f"audiocli.ops.{module_name}"), module_name)
        _assert_audio_buffer(fn(source, **kwargs), source)


def test_extended_pedalboard_op_choices_are_validated() -> None:
    ladder = validate_capability_params("builtin.filter.ladder", {"mode": "LPF24"})
    bad_ladder = validate_capability_params("builtin.filter.ladder", {"mode": "bogus"})
    gsm = validate_capability_params("builtin.filter.gsm", {"quality": "Linear"})
    bad_gsm = validate_capability_params("builtin.filter.gsm", {"quality": "bogus"})

    assert ladder.valid is True
    assert bad_ladder.valid is False
    assert bad_ladder.errors[0].code == "invalid_choice"
    assert gsm.valid is True
    assert bad_gsm.valid is False
    assert bad_gsm.errors[0].code == "invalid_choice"
