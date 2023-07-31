from AudioCLI.src.client import BaseCommandCategory
from AudioCLI.src.util import chunks, load_file, save_to_file
from termcolor import cprint
import os
import torch
import torchaudio.transforms as T
from torch.nn import functional as F
from tqdm import tqdm, trange
import importlib
import concurrent.futures
from aeiou.datasets import PhaseFlipper, Mono, Stereo, RandPool
import random

"""
Process target audio paths with various effects.
-o can be appended to overwrite the original file.
-pt can be appended to save as .pt (pytorch) file.
"""


class ProcessCommands(BaseCommandCategory):
    """
    Process target audio paths with various effects.
    """

    def _get_info(self):
        return {
            "name": "process",
            "description": "Process target paths.",
        }

    # Declare exposed commands
    def _get_commands(self):
        return {
            "remove_silent": self.remove_silent,
            "resample": self.resample,
            "stereo": self.stereo,
            "mono": self.mono,
            "chunk": self.chunk,
            "bitdepth": self.bitdepth,
            "phaseflip": self.phaseflip,
            "noise": self.noise,
            "pool": self.pool,
            "pitch": self.pitch,
            "hook": self.hook,
        }

    def _audio_to_batched(self, audio):
        if len(audio.shape) == 3:
            itaudio = audio
        elif len(audio.shape) == 2:
            itaudio = [audio]
        elif len(audio.shape) == 1:
            audio = audio.unsqueeze(0)
            itaudio = [audio]
        return itaudio

    def _get_prog(self, input_batches, text):
        return tqdm(
            desc=text,
            total=sum(min(len(list1), len(list2)) for list1, list2 in input_batches),
        )

    def _can_process(self):
        return True

    # Define commands
    def remove_silent(self, threshold: float = 0.01):
        """
        Remove audio files in target folders that are silent or below the threshold.
        WARNING: This will delete files.

        Args:\n
            threshold (float): Threshold for silence detection\n
        """
        input_batches = self.client.get_save_paths(f"UNUSED")
        prog = self._get_prog(input_batches, "Removing silent")

        def remove_silent_batch(args):
            try:
                filepath, _ = args
                audio, sr = load_file(filepath)
                if audio.max() < float(threshold):
                    os.remove(filepath)
                prog.update(1)
            except Exception as e:
                print(e)

        if input_batches:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.client.batch_size
            ) as executor:
                for batch in input_batches:
                    tasks = list(zip(*batch))
                    executor.map(remove_silent_batch, tasks)

    def resample(self, sample_rate: int):
        """
        Resample all audio files in the current target paths to a new sample rate.

        Appending ID: _resampled_{sample_rate}

        Args:\n
            sample_rate (int): New sample rate\n
        """
        input_batches = self.client.get_save_paths(f"_resampled_{sample_rate}")
        prog = self._get_prog(input_batches, "Resampling")

        def resample_batch(args):
            try:
                filepath, save_path, _ = args
                audio, sr = load_file(filepath)
                audio.to(self.client.device)
                aug_tf = T.Resample(int(sr), int(sample_rate))
                auged = aug_tf(audio)
                save_to_file(
                    save_path,
                    auged,
                    int(sample_rate),
                    pt_save=self.client.one_shot_args["pt_save"],
                )
                prog.update(1)
            except Exception as e:
                print(e)

        if input_batches:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.client.batch_size
            ) as executor:
                for batch in input_batches:
                    tasks = [
                        (filepath, save_path, sample_rate)
                        for filepath, save_path in zip(*batch)
                    ]
                    executor.map(resample_batch, tasks)

    def phaseflip(self):
        """
        Flip phase of all audio files in the current target paths.

        Appending ID: _phaseflipped
        """
        input_batches = self.client.get_save_paths(f"_phaseflipped")
        prog = self._get_prog(input_batches, "Phase flipping")

        def phaseflip_batch(args):
            try:
                filepath, save_path = args
                audio, sr = load_file(filepath)
                audio.to(self.client.device)
                aug_tf = PhaseFlipper(p=1.0)
                auged = aug_tf(audio)
                save_to_file(
                    save_path,
                    auged,
                    int(sr),
                    pt_save=self.client.one_shot_args["pt_save"],
                )
                prog.update(1)
            except Exception as e:
                print(e)

        if input_batches:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.client.batch_size
            ) as executor:
                for batch in input_batches:
                    tasks = list(zip(*batch))
                    executor.map(phaseflip_batch, tasks)

    def noise(self, noise_level: float):
        """
        Add noise to all audio files in the current target paths.

        Appending ID: _noise_{noise_level}

        Args:\n
            noise_level (float): Noise level\n
        """
        input_batches = self.client.get_save_paths(f"_noise_{noise_level}")
        prog = self._get_prog(input_batches, "Adding noise")

        def noise_batch(args):
            try:
                filepath, save_path = args
                audio, sr = load_file(filepath)
                audio.to(self.client.device)
                itaudio = self._audio_to_batched(audio)
                for signal in itaudio:
                    auged = signal + float(noise_level) * random.random() * (
                        2 * torch.rand_like(signal) - 1
                    )
                    save_to_file(
                        save_path,
                        auged,
                        int(sr),
                        pt_save=self.client.one_shot_args["pt_save"],
                    )
                prog.update(1)
            except Exception as e:
                print(e)

        if input_batches:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.client.batch_size
            ) as executor:
                for batch in input_batches:
                    tasks = list(zip(*batch))
                    executor.map(noise_batch, tasks)

    def pool(self):
        """
        Do avgpool operation on audio files in the current target paths, with random-sized kernel.

        Appending ID: _pooled
        """
        input_batches = self.client.get_save_paths(f"_pooled")
        prog = self._get_prog(input_batches, "Pooling")

        def pool_batch(args):
            try:
                filepath, save_path = args
                audio, sr = load_file(filepath)
                audio.to(self.client.device)
                aug_tf = RandPool(p=1.0)
                auged = aug_tf(audio)
                save_to_file(
                    save_path,
                    auged,
                    int(sr),
                    pt_save=self.client.one_shot_args["pt_save"],
                )
                prog.update(1)
            except Exception as e:
                print(e)

        if input_batches:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.client.batch_size
            ) as executor:
                for batch in input_batches:
                    tasks = list(zip(*batch))
                    executor.map(pool_batch, tasks)

    def pitch(self, pitch: int):
        """
        Change pitch of all audio files in the current target paths to a new pitch.

        Appending ID: _pitched_{pitch}

        Args:\n
            pitch (int): New pitch\n
        """
        plus = "+" if int(pitch) > 0 else ""
        input_batches = self.client.get_save_paths(f"_pitched_{plus}{pitch}")
        prog = self._get_prog(input_batches, "Pitch shifting")

        def pitch_batch(args):
            try:
                filepath, save_path = args
                audio, sr = load_file(filepath)
                audio.to(self.client.device)
                itaudio = self._audio_to_batched(audio)
                aug_tf = T.PitchShift(int(sr), int(pitch))
                for signal in itaudio:
                    auged = aug_tf(signal)
                    save_to_file(
                        save_path,
                        auged,
                        int(sr),
                        pt_save=self.client.one_shot_args["pt_save"],
                    )
                prog.update(1)
            except Exception as e:
                print(e)

        if input_batches:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                for batch in input_batches:
                    tasks = list(zip(*batch))
                    executor.map(pitch_batch, tasks)

    def bitdepth(self, bit_depth: int):
        """
        Convert all audio files in the current target paths to a new bit depth.

        Appending ID: _bitdepth_{bit_depth}

        Args:\n
            bit_depth (int): New bit depth\n
        """

        if bit_depth not in [8, 16, 24, 32]:
            cprint("Error: bit depth must be 8, 16, 24, or 32.", color="red")
            return

        input_batches = self.client.get_save_paths(f"_bitdepth_{bit_depth}")
        prog = self._get_prog(input_batches, "Changing bit depth")

        def bitdepth_batch(args):
            try:
                filepath, save_path = args
                audio, sr = load_file(filepath)
                audio.to(self.client.device)
                bit_depth = [int(bit_depth)] * len(filepath)
                save_to_file(
                    save_path,
                    audio,
                    int(sr),
                    bits=bit_depth,
                    pt_save=self.client.one_shot_args["pt_save"],
                )
                prog.update(1)
            except Exception as e:
                print(e)

        if input_batches:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.client.batch_size
            ) as executor:
                for batch in input_batches:
                    tasks = list(zip(*batch))
                    executor.map(bitdepth_batch, tasks)

    def stereo(self):
        """
        Convert all audio files in the current target paths to stereo.

        Appending ID: _stereo
        """
        input_batches = self.client.get_save_paths("_stereo")
        prog = self._get_prog(input_batches, "Converting to stereo")

        def stereo_batch(args):
            try:
                filepath, save_path = args
                audio, sr = load_file(filepath)
                audio.to(self.client.device)
                aug_tf = Stereo()
                auged = aug_tf(audio)
                save_to_file(
                    save_path,
                    auged,
                    int(sr),
                    pt_save=self.client.one_shot_args["pt_save"],
                )
                prog.update(1)
            except Exception as e:
                print(e)

        if input_batches:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.client.batch_size
            ) as executor:
                for batch in input_batches:
                    tasks = list(zip(*batch))
                    executor.map(stereo_batch, tasks)

    def mono(self):
        """
        Convert all audio files in the current target paths to mono.

        Appending ID: _mono
        """
        input_batches = self.client.get_save_paths("_mono")
        prog = self._get_prog(input_batches, "Converting to mono")

        def mono_batch(args):
            try:
                filepath, save_path = args
                audio, sr = load_file(filepath)
                audio.to(self.client.device)
                aug_tf = Mono()
                auged = aug_tf(audio)
                save_to_file(
                    save_path,
                    auged,
                    int(sr),
                    pt_save=self.client.one_shot_args["pt_save"],
                )
                prog.update(1)
            except Exception as e:
                print(e)

        if input_batches:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.client.batch_size
            ) as executor:
                for batch in prog:
                    tasks = list(zip(*batch))
                    executor.map(mono_batch, tasks)

    def chunk(self, length: float, pad: bool = True, clean: bool = False):
        """
        Splits all audio files in the current target paths into chunks of a specified length. If the
        last piece does not contain enough audio data, it pads the remaining space with silence.

        Appending ID: _chunked_{length}

        Args:\n
            length (float): Length of each chunk in seconds\n
            pad (bool): If True, pad the last chunk to 'length' with silence if it doesn't contain enough audio data\n
            clean (bool): If True, remove the original file after chunking\n
        """
        length = int(length)
        input_batches = self.client.get_save_paths(f"_chunked_{length}")
        prog = self._get_prog(input_batches, "Chunking")

        def chunk_batch(args):
            try:
                filepath, save_path = args
                audio, sr = load_file(filepath)
                audio.to(self.client.device)
                n_chunks = audio.shape[1] / length
                chunks = []
                index = 1
                for i in range(0, int(n_chunks)):
                    isave_path = (
                        os.path.splitext(save_path)[0]
                        + f"_{index}"
                        + os.path.splitext(save_path)[1]
                    )
                    chunk = audio[:, i * length : (i + 1) * length]
                    chunks.append(chunk)
                    save_to_file(
                        isave_path,
                        chunk,
                        int(sr),
                        pt_save=self.client.one_shot_args["pt_save"],
                    )
                    index += 1

                last_chunk = audio[:, int(n_chunks) * length :]
                last_save_path = (
                    os.path.splitext(save_path)[0]
                    + f"_{index}"
                    + os.path.splitext(save_path)[1]
                )
                if pad:
                    last_chunk = F.pad(last_chunk, (0, length - last_chunk.shape[1]))
                save_to_file(
                    last_save_path,
                    last_chunk,
                    int(sr),
                    pt_save=self.client.one_shot_args["pt_save"],
                )
                if clean:
                    os.remove(filepath)
                prog.update(1)
            except Exception as e:
                print(e)

        if input_batches:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.client.batch_size
            ) as executor:
                for batch in input_batches:
                    tasks = list(zip(*batch))
                    executor.map(chunk_batch, tasks)

    def hook(self, python_file: str, function: str):
        """
        Process audio files using an external function in an external python file.
        Function will recieve:
            - A torch.Tensor of shape batch_size x channels x n_samples.
            - A list of potential save paths for the files in the batch.
            - The sample rate of the audio files.
        The function must return a torch.Tensor of shape batch_size x channels x n_samples or None.

        Append ID: _{function}

        Args:\n
            python_file (str): Path to python file containing function\n
            function (str): Name of function to use\n
        """
        input_batches = self.client.get_save_paths(f"_{function}")
        prog = self._get_prog(input_batches, f"Processing with function: {function}")

        # Load python file and import function
        spec = importlib.util.spec_from_file_location("module.name", python_file)
        foo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(foo)
        func = getattr(foo, function)

        def hook_batch(args):
            try:
                filepaths, save_paths = args
                audio, sr = load_file(filepaths)
                audio.to(self.client.device)
                auged = func(audio, save_paths, int(sr))
                if auged is not None:
                    save_to_file(
                        save_paths,
                        auged,
                        int(sr),
                        pt_save=self.client.one_shot_args["pt_save"],
                    )
                prog.update(1)
            except Exception as e:
                print(e)

        if input_batches:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.client.batch_size
            ) as executor:
                for batch in input_batches:
                    tasks = list(zip(*batch))
                    executor.map(hook_batch, tasks)

    def file(self, acli_file: str):
        """
        Run acli commands from a file in batch.

        Args:\n
            acli_file (str): Path to .acli file.\n
        """
        with open(acli_file, "r") as f:
            self.client.batch(f)
