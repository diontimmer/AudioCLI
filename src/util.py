from pedalboard.io import AudioFile
import torch
import torchaudio


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
