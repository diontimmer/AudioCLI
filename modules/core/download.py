from src.client import BaseCommandCategory
from termcolor import cprint
import os


class DownloadCommands(BaseCommandCategory):
    # Set command name and description
    """
    Various commands for downloading.
    """

    def _get_info(self):
        return {
            "name": "download",
            "description": "Various commands for downloading.",
        }

    # Declare exposed commands
    def _get_commands(self):
        return {}
