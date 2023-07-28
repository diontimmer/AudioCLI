from src.client import BaseCommandCategory
from src.util import chunks, load_file, Stereo, Mono
from termcolor import cprint
import os
import torch
import torchaudio
import torchaudio.transforms as T


class ProcessCommands(BaseCommandCategory):
    def get_batches(self, id_str):
        if not self.client.target_data.contains_data():
            cprint("No data loaded.", color="red")
            return None
        if self.client.output_dir is None:
            cprint(
                "Warning: An output directory is not set. Running this command will overwrite your files.",
                color="red",
            )
            confirm = input(
                "Type yes / y to continue and overwrite or no / n to rename and keep files in the same folder. You can also type in an output directory to set it."
            )
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
            batches = []
            for fp_batch in chunks(
                self.client.target_data.file_paths, self.client.batch_size
            ):
                audios = []
                save_paths = []
                srs = []
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

                    input_audio, input_sr = load_file(file_path)
                    audios.append(input_audio)
                    save_paths.append(save_path)
                    srs.append(input_sr)

                audios = torch.stack(audios, dim=0)
                batches.append((audios, save_paths, srs))
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
        }

    # Define commands
    def resample(self, sample_rate: int):
        """
        Resample all audio files in the current target paths to a new sample rate.

        Args:
            sample_rate (int): New sample rate
        """
        input_batches = self.get_batches(f"_resampled_{sample_rate}")
        for batch in input_batches:
            for audio, save_path, sr in zip(*batch):
                aug_tf = T.Resample(int(sr), int(sample_rate))
                auged = aug_tf(audio)
                torchaudio.save(save_path, auged, int(sample_rate))

    def stereo(self):
        """
        Convert all audio files in the current target paths to stereo.
        """
        input_batches = self.get_batches("_stereo")
        for batch in input_batches:
            for audio, save_path, sr in zip(*batch):
                aug_tf = Stereo()
                auged = aug_tf(audio)
                torchaudio.save(save_path, auged, int(sr))

    def mono(self):
        """
        Convert all audio files in the current target paths to mono.
        """
        input_batches = self.get_batches("_mono")
        for batch in input_batches:
            for audio, save_path, sr in zip(*batch):
                aug_tf = Mono()
                auged = aug_tf(audio)
                torchaudio.save(save_path, auged, int(sr))
