from .target_data import TargetData
import icli
import os
from termcolor import cprint
from .util import chunks, load_file
import torch
from .processing import resample, example_func
from pedalboard.io import AudioFile
import torchaudio


class InteractiveClient(icli.ArgumentParser):
    def __init__(self, *args, **kwargs):
        self.target_data = TargetData()
        self.output_dir = None  # Store the output directory
        self.batch_size = 3  # Store the batch size, default is 3
        super().__init__(*args, **kwargs)

    def run(self, _cmd, _type=None, _command=None, **kwargs):
        if _cmd == "target":
            if _command == "set":
                for path in kwargs["paths"]:
                    if not os.path.exists(path):
                        cprint(
                            f"Error: {path} does not exist. Try escaping slashes/adding quotation marks?",
                            color="red",
                        )
                        return

                amount = self.target_data.scan(kwargs["paths"])
                cprint(f"Target paths set to {kwargs['paths']}", color="yellow")
                cprint(f"Found {amount} audio files.", color="green")
            elif _command == "info":
                if self.target_data.contains_data():
                    cprint(
                        f"Loaded paths: {self.target_data.search_paths}", color="yellow"
                    )
                    cprint(
                        f"Number of audio files: {len(self.target_data.file_paths)}",
                        color="green",
                    )
                else:
                    cprint("No target paths have been set.", color="red")

        # Handle the "batch_size" command
        elif _cmd == "batch_size":
            if _command == "set":
                self.batch_size = kwargs["size"]
                cprint(f"Batch size set to {self.batch_size}", color="yellow")

        # Handle the "output" command
        elif _cmd == "output":
            if _command == "set":
                self.output_dir = kwargs["dir"]
                cprint(f"Output directory set to {self.output_dir}", color="yellow")
                os.makedirs(self.output_dir, exist_ok=True)

        # Handle the "process" command
        elif _cmd == "process":
            if self.target_data.contains_data():
                if self.output_dir is None:
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
                        self.output_dir = confirm
                        cprint(
                            f"Output directory set to {self.output_dir}", color="yellow"
                        )

                for fp_batch in chunks(self.target_data.file_paths, self.batch_size):
                    batch = []
                    save_paths = []
                    srs = []
                    save_audio_data = False
                    for file_path in fp_batch:
                        if self.output_dir is None:
                            save_path = (
                                file_path
                                if output_overwrite
                                else os.path.splitext(file_path)[0]
                                + _command
                                + os.path.splitext(file_path)[1]
                            )
                        else:
                            save_path = os.path.join(
                                self.output_dir, os.path.basename(file_path)
                            )

                        input_audio, input_sr = load_file(file_path)
                        batch.append(input_audio)
                        save_paths.append(save_path)
                        srs.append(input_sr)

                    batch = torch.stack(batch, dim=0)

                    if _command == "resample":
                        auged, srs = resample(batch, srs, kwargs["sample_rate"])
                        save_audio_data = True
                    elif _command == "other_command":
                        auged, srs = example_func(
                            batch, srs, kwargs["param1"], kwargs["param2"]
                        )
                    else:
                        cprint(f"Error: Unknown command {_command}", color="red")
                        return

                    if save_audio_data:
                        for save_path, auged, sr in zip(save_paths, auged, srs):
                            if save_path.endswith(".mp3"):
                                with AudioFile(
                                    save_path, "w", int(sr), num_channels=auged.shape[0]
                                ) as f:
                                    f.write(auged.numpy())
                            else:
                                torchaudio.save(save_path, auged, sr)

                cprint("Done!", color="green")

                # need to add moar

            else:
                cprint("No target paths have been set.", color="red")
