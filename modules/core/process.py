from src.client import BaseCommandCategory
from src.util import chunks, load_file, Stereo, Mono, save_to_file
from termcolor import cprint
import os
import torch
import torchaudio.transforms as T
from torch.nn import functional as F
from tqdm import tqdm, trange
import math


class ProcessCommands(BaseCommandCategory):
    def get_save_paths(self, id_str):
        if not self.client.target_data.contains_data():
            cprint("No data loaded.", color="red")
            return None
        if self.client.output_dir is None:
            cprint(
                "Warning: An output directory is not set. Running this command will overwrite your files.",
                color="red",
            )
            confirm = input(
                "Type yes / y to continue and overwrite or no / n to rename and keep files in the same folder. You can also type in an output directory to set it.\nType cancel / c to cancel.\n"
            )
            if confirm.lower() in ["c", "cancel"]:
                return None
            if confirm.lower() in ["yes", "y"]:
                output_overwrite = True
            elif confirm.lower() in ["no", "n"]:
                output_overwrite = False
            else:
                self.client.output_dir = confirm
                cprint(
                    f"Output directory set to {self.client.output_dir}",
                    color="yellow",
                )
                os.makedirs(self.client.output_dir, exist_ok=True)
            batches = []
            chunked = chunks(self.client.target_data.file_paths, self.client.batch_size)
            for fp_batch in chunked:
                save_paths = []
                for file_path in fp_batch:
                    if self.client.output_dir is None:
                        save_path = (
                            file_path
                            if output_overwrite
                            else os.path.splitext(file_path)[0]
                            + id_str
                            + os.path.splitext(file_path)[1]
                        )
                    else:
                        save_path = os.path.join(
                            self.client.output_dir, os.path.basename(file_path)
                        )
                    save_paths.append(save_path)

                batches.append((fp_batch, save_paths))
            return batches

    def get_info(self):
        return {
            "name": "process",
            "description": "Process target paths.",
        }

    # Declare exposed commands
    def get_commands(self):
        return {
            "resample": self.resample,
            "stereo": self.stereo,
            "mono": self.mono,
            "chunk": self.chunk,
        }

    # Define commands
    def resample(self, sample_rate: int):
        """
        Resample all audio files in the current target paths to a new sample rate.

        Args:
            sample_rate (int): New sample rate
        """
        input_batches = self.get_save_paths(f"_resampled_{sample_rate}")
        if input_batches:
            for batch in tqdm(input_batches, desc="Resampling"):
                for filepath, save_path in zip(*batch):
                    audio, sr = load_file(filepath)
                    aug_tf = T.Resample(int(sr), int(sample_rate))
                    auged = aug_tf(audio)
                    auged = auged.to("cpu")
                    save_to_file(save_path, auged, int(sample_rate))

    def stereo(self):
        """
        Convert all audio files in the current target paths to stereo.
        """
        input_batches = self.get_save_paths("_stereo")
        if input_batches:
            for batch in tqdm(input_batches, desc="Converting to stereo"):
                for filepath, save_path in zip(*batch):
                    audio, sr = load_file(filepath)
                    aug_tf = Stereo()
                    auged = aug_tf(audio)
                    auged = auged.to("cpu")
                    save_to_file(save_path, auged, int(sr))

    def mono(self):
        """
        Convert all audio files in the current target paths to mono.
        """
        input_batches = self.get_save_paths("_mono")
        if input_batches:
            for batch in tqdm(input_batches, desc="Converting to mono"):
                for filepath, save_path in zip(*batch):
                    audio, sr = load_file(filepath)
                    aug_tf = Mono()
                    auged = aug_tf(audio)
                    auged = auged.to("cpu")
                    save_to_file(save_path, auged, int(sr))

    def chunk(self, length: float, pad: bool = True):
        """
        Splits all audio files in the current target paths into chunks of a specified length. If the
        last piece does not contain enough audio data, it pads the remaining space with silence.

        Args:
            length (float): Length of each chunk in seconds
            pad (bool): If True, pad the last chunk to 'length' with silence if it doesn't contain enough audio data
        """
        length = int(length)
        input_batches = self.get_save_paths(f"_chunked_{length}")
        if input_batches:
            for batch in tqdm(input_batches, desc="Chunking"):
                for filepath, save_path in zip(*batch):
                    audio, sr = load_file(filepath)
                    n_chunks = audio.shape[1] / length
                    chunks = []
                    index = 1  #
                    for i in trange(0, int(n_chunks)):
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
                        last_chunk = F.pad(
                            last_chunk, (0, length - last_chunk.shape[1])
                        )
                    save_to_file(last_save_path, last_chunk, int(sr))
