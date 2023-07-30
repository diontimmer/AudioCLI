from pedalboard.io import AudioFile
import torch
import torchaudio
import torch.nn as nn
import re
import os


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


def save_to_file(paths, audios, srs, bits=None, pt_save=False):
    paths = [paths] if not isinstance(paths, list) else paths
    audios = [audios] if not isinstance(audios, list) else audios
    srs = [srs] if not isinstance(srs, list) else srs
    bits = [bits] if not isinstance(bits, list) else bits
    for save_path, audio, sr, bit in zip(paths, audios, srs, bits):
        audio = audio.to("cpu")
        audio = audio.detach()
        if pt_save:
            save_path = os.path.splitext(save_path)[0] + ".pt"
            torch.save(audio, save_path)
            return
        if save_path.endswith(".mp3"):
            with AudioFile(save_path, "w", int(sr), num_channels=audio.shape[0]) as f:
                f.write(audio.numpy())
        else:
            if len(audio.shape) == 1:
                audio = audio.unsqueeze(0)
            if bit:
                torchaudio.save(save_path, audio, sr, bits_per_sample=bit)
            else:
                torchaudio.save(save_path, audio, sr)


def extract_arg_help(arg, docstring):
    """
    Given an argument name and a docstring, try to extract a helpful
    message for the argument from the docstring.

    Parameters:
        arg (str): the name of the argument
        docstring (str): the docstring to extract the message from

    Returns:
        str: a helpful message, or a default message if none could be found.
    """
    if docstring is None:
        return "No help text available"

    args_section_match = re.search(r"Args:(.*)", docstring, re.DOTALL)
    if not args_section_match:
        return "No help text available"

    args_section = args_section_match.group(1)
    for line in args_section.split("\n"):
        arg_match = re.match(r"\s*" + arg + r"\s*\((.*?)\):\s*(.*)", line)
        if arg_match:
            # Return the rest of the line, after the argument type
            return arg_match.group(2)

    # If we've got here, we couldn't find a helpful message for this argument
    return "No help text available"
