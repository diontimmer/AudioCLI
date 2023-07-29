from src.client import InteractiveClient
from termcolor import cprint
import sys
import os


def main():
    # get file path
    client = InteractiveClient()
    client.parser.interactive_history_file = os.path.join(
        os.path.dirname(os.path.realpath(__file__)), ".acli_history"
    )
    client.parser.sections = {
        value.name: [] for key, value in client.categories.items()
    }

    cprint(f"Loaded {len(client.categories)} categories.", color="green")

    if len(sys.argv) > 1:
        client.parser.interactive()
    else:
        cprint(
            "\nWelcome to AudioCLI! Augmenting in batch | By Dion Timmer", color="green"
        )
        cprint("-----------------------------------------------------", color="green")
        cprint(
            "Please set your target folder(s) by typing 'target set <path>, <path>, <path>'. Multiple are optional.",
            color="green",
        )
        cprint(
            "Please set your output folder by typing 'target output <path>'. You will be presented the choice to overwrite or rename the files if not set.",
            color="green",
        )
        cprint("-----------------------------------------------------\n", color="green")
        client.parser.interactive()


if __name__ == "__main__":
    main()
