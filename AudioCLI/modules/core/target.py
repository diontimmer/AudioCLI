from AudioCLI.src.client import BaseCommandCategory
from AudioCLI.src.target_data import TargetData
from termcolor import cprint
import os


class TargetCommands(BaseCommandCategory):
    # Set command name and description
    def _get_info(self):
        return {
            "name": "target",
            "description": "Set target path options.",
        }

    # Declare exposed commands
    def _get_commands(self):
        return {
            "set": self.set,
            "clear": self.clear,
            "batch_size": self.batch_size,
            "info": self.info,
            "output": self.output,
            "device": self.device,
        }

    # Define commands
    def set(self, paths: list, recursive: bool = True):
        """
        Set target paths of the current session.

        Args:\n
            paths (list): Paths to target\n
            recursive (bool): Whether to recursively scan directories\n
        """
        if recursive:  # if recursive
            cprint("Recursively scanning directories.", color="yellow")
        else:
            cprint("Scanning directories.", color="yellow")
        for path in paths:
            if not os.path.exists(path):
                cprint(
                    f"Error: {path} does not exist. Try escaping slashes/adding quotation marks?",
                    color="red",
                )
                return
        amount = self.client.target_data.scan(paths, recursive=recursive)

    def clear(self):
        """
        Clear target paths of the current session.
        """
        self.client.target_data = TargetData()
        cprint("Target paths cleared.", color="green")

    def batch_size(self, size: int):
        """
        Set batch size of the current session.

        Args:\n
            size (int): Batch size\n
        """
        self.client.batch_size = size
        cprint(f"Batch size set to {self.client.batch_size}", color="yellow")

    def info(self):
        """
        Print information about the current target paths.
        """
        if not self.client.target_data.contains_data():
            cprint("No target paths have been set.", color="red")

        cprint(f"Batch size: {self.client.batch_size}", color="green")
        cprint(f"Output directory: {self.client.output_dir}", color="green")
        cprint(f"Processing device: {self.client.device}", color="green")

    def output(self, path: str):
        """
        Set output directory of the current session.

        Args:\n
            path (str): Output directory\n
        """
        if path == "clear":
            self.client.output_dir = None
            cprint("Output directory cleared.", color="green")
            return
        self.client.output_dir = path
        cprint(f"Output directory set to {self.client.output_dir}", color="green")
        os.makedirs(self.client.output_dir, exist_ok=True)

    def device(self, device: str):
        """
        Set processing device of the current session.

        Args:\n
            device (str): Processing device\n
        """
        self.client.device = device
        cprint(f"Processing device set to {self.client.device}", color="green")
