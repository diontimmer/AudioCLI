from src.client import BaseCommandCategory
from src.util import chunks, load_file, Stereo, Mono, save_to_file
from termcolor import cprint
import os
import torch
import torchaudio.transforms as T
from torch.nn import functional as F
from tqdm import tqdm, trange
import math
import concurrent.futures

"""
Process target audio paths with various effects.
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
            "resample": self.resample,
            "stereo": self.stereo,
            "mono": self.mono,
            "chunk": self.chunk,
            "bitdepth": self.bitdepth,
        }

    # Define commands

    def resample(self, sample_rate: int):
        """
        Resample all audio files in the current target paths to a new sample rate.

        Args:\n
            sample_rate (int): New sample rate\n
        """
        input_batches = self.client.get_save_paths(f"_resampled_{sample_rate}")

        def resample_batch(args):
            filepath, save_path, _ = args
            audio, sr = load_file(filepath)
            aug_tf = T.Resample(int(sr), int(sample_rate))
            auged = aug_tf(audio)
            save_to_file(save_path, auged, int(sample_rate))

        if input_batches:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.client.batch_size
            ) as executor:
                for batch in tqdm(input_batches, desc="Resampling"):
                    tasks = [
                        (filepath, save_path, sample_rate)
                        for filepath, save_path in zip(*batch)
                    ]
                    executor.map(resample_batch, tasks)

    def bitdepth(self, bit_depth: int):
        """
        Convert all audio files in the current target paths to a new bit depth.

        Args:\n
            bit_depth (int): New bit depth\n
        """

        if bit_depth not in [8, 16, 24, 32]:
            cprint("Error: bit depth must be 8, 16, 24, or 32.", color="red")
            return

        input_batches = self.client.get_save_paths(f"_bitdepth_{bit_depth}")

        def bitdepth_batch(args):
            filepath, save_path = args
            audio, sr = load_file(filepath)
            bit_depth = [int(bit_depth)] * len(filepath)
            save_to_file(save_path, audio, int(sr), bits=bit_depth)

        if input_batches:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.client.batch_size
            ) as executor:
                for batch in tqdm(input_batches, desc="Changing bit depth"):
                    tasks = list(zip(*batch))
                    executor.map(bitdepth_batch, tasks)

    def stereo(self):
        """
        Convert all audio files in the current target paths to stereo.
        """
        input_batches = self.client.get_save_paths("_stereo")

        def stereo_batch(args):
            filepath, save_path = args
            audio, sr = load_file(filepath)
            aug_tf = Stereo()
            auged = aug_tf(audio)
            save_to_file(save_path, auged, int(sr))

        if input_batches:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.client.batch_size
            ) as executor:
                for batch in tqdm(input_batches, desc="Converting to stereo"):
                    tasks = list(zip(*batch))
                    executor.map(stereo_batch, tasks)

    def mono(self):
        """
        Convert all audio files in the current target paths to mono.
        """
        input_batches = self.client.get_save_paths("_mono")

        def mono_batch(args):
            filepath, save_path = args
            audio, sr = load_file(filepath)
            aug_tf = Mono()
            auged = aug_tf(audio)
            save_to_file(save_path, auged, int(sr))

        if input_batches:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.client.batch_size
            ) as executor:
                for batch in tqdm(input_batches, desc="Converting to mono"):
                    tasks = list(zip(*batch))
                    executor.map(mono_batch, tasks)

    def chunk(self, length: float, pad: bool = True, clean: bool = False):
        """
        Splits all audio files in the current target paths into chunks of a specified length. If the
        last piece does not contain enough audio data, it pads the remaining space with silence.

        Args:\n
            length (float): Length of each chunk in seconds\n
            pad (bool): If True, pad the last chunk to 'length' with silence if it doesn't contain enough audio data\n
            clean (bool): If True, remove the original file after chunking\n
        """
        length = int(length)
        input_batches = self.client.get_save_paths(f"_chunked_{length}")

        def chunk_batch(args):
            filepath, save_path = args
            audio, sr = load_file(filepath)
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
                save_to_file(isave_path, chunk, int(sr))
                index += 1

            last_chunk = audio[:, int(n_chunks) * length :]
            last_save_path = (
                os.path.splitext(save_path)[0]
                + f"_{index}"
                + os.path.splitext(save_path)[1]
            )
            if pad:
                last_chunk = F.pad(last_chunk, (0, length - last_chunk.shape[1]))
            save_to_file(last_save_path, last_chunk, int(sr))
            if clean:
                os.remove(filepath)

        if input_batches:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.client.batch_size
            ) as executor:
                for batch in tqdm(input_batches, desc="Chunking"):
                    tasks = list(zip(*batch))
                    executor.map(chunk_batch, tasks)
