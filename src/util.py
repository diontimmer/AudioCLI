from pedalboard.io import AudioFile
import torch
import torchaudio
import torch.nn as nn


class Mono(nn.Module):
    def __call__(self, signal):
        return torch.mean(signal, dim=0) if len(signal.shape) > 1 else signal


class Stereo(nn.Module):
    def __call__(self, signal):
        signal_shape = signal.shape
        # Check if it's mono
        if len(signal_shape) == 1:  # s -> 2, s
            signal = signal.unsqueeze(0).repeat(2, 1)
        elif len(signal_shape) == 2:
            if signal_shape[0] == 1:  # 1, s -> 2, s
                signal = signal.repeat(2, 1)
            elif signal_shape[0] > 2:  # ?, s -> 2,s
                signal = signal[:2, :]

        return signal


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def load_file(filename):
    ext = filename.split(".")[-1]
    if ext == "mp3":
        with AudioFile(filename) as f:
            audio = f.read(f.frames)
            audio = torch.from_numpy(audio)
            in_sr = f.samplerate
    else:
        audio, in_sr = torchaudio.load(filename, format=ext)
    return audio, in_sr


def save_to_file(paths, audios, srs):
    for save_path, audio, sr in zip(paths, audios, srs):
        if save_path.endswith(".mp3"):
            with AudioFile(save_path, "w", int(sr), num_channels=audio.shape[0]) as f:
                f.write(audio.numpy())
        else:
            torchaudio.save(save_path, audio, sr)
