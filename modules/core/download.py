# from src.client import BaseCommandCategory
# from termcolor import cprint
# import os


# class DownloadCommands(BaseCommandCategory):
#     # Set command name and description
#     def get_info(self):
#         return {
#             "name": "download",
#             "description": "Various commands for downloading.",
#         }

#     # Declare exposed commands
#     def get_commands(self):
#         return {
#             "set": self.set,
#             "batch_size": self.batch_size,
#             "info": self.info,
#             "output": self.output,
#             "device": self.device,
#         }

#     # Define commands
#     def set(self, paths: list):
#         """
#         Set target paths of the current session.

#         Args:
#             paths (list): Paths to target
#         """
#         for path in paths:
#             if not os.path.exists(path):
#                 cprint(
#                     f"Error: {path} does not exist. Try escaping slashes/adding quotation marks?",
#                     color="red",
#                 )
#                 return
#         amount = self.client.target_data.scan(paths)
#         cprint(f"Target paths set to {paths}", color="yellow")
#         cprint(f"Found {amount} audio files.", color="green")

#     def batch_size(self, size: int):
#         """
#         Set batch size of the current session.

#         Args:
#             size (int): Batch size
#         """
#         self.client.batch_size = size
#         cprint(f"Batch size set to {self.client.batch_size}", color="yellow")

#     def info(self):
#         """
#         Print information about the current target paths.
#         """
#         if self.client.target_data.contains_data():
#             cprint(
#                 f"Loaded paths: {self.client.target_data.search_paths}", color="green"
#             )
#             cprint(
#                 f"Number of audio files: {len(self.client.target_data.file_paths)}",
#                 color="green",
#             )
#             cprint(f"Batch size: {self.client.batch_size}", color="green")
#         else:
#             cprint("No target paths have been set.", color="red")

#     def output(self, path: str):
#         """
#         Set output directory of the current session.

#         Args:
#             path (str): Output directory
#         """
#         self.client.output_dir = path
#         cprint(f"Output directory set to {self.output_dir}", color="yellow")
#         os.makedirs(self.output_dir, exist_ok=True)

#     def device(self, device: str):
#         """
#         Set processing device of the current session.

#         Args:
#             device (str): Processing device
#         """
#         self.client.device = device
#         cprint(f"Processing device set to {self.client.device}", color="yellow")
