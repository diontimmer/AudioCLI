from src.client import InteractiveClient
from termcolor import cprint
import sys
import os


def main():
    # get file path
    client = InteractiveClient()
    client.load_from_settings()
    client.parser.interactive_history_file = os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "h.acli_history"
    )
    client.parser.sections = {
        value.name: [] for key, value in client.categories.items()
    }

    cprint(f"Loaded {len(client.categories)} categories.", color="green")

    if len(sys.argv) > 1:
        client.parser.interactive()
    else:
        cprint(
            "\nWelcome to AudioCLI! Augmenting in batch | By Dion Timmer", color="cyan"
        )
        cprint("-----------------------------------------------------", color="cyan")
        cprint(
            r"""
                ; 
                ;;
                ;';.
                ;  ;;
                ;   ;;
                ;    ;;
                ;    ;;
                ;   ;'
                ;  ' 
           ,;;;,; 
           ;;;;;;
           `;;;;'
        """,
            color="magenta",
        )
        cprint("-----------------------------------------------------", color="cyan")
        cprint(
            "Please set your target folder(s) by typing 'target set <path>, <path>, <path>'. Multiples are allowed.",
            color="yellow",
        )
        cprint(
            "Please set your output folder by typing 'target output <path>'.\nYou will be presented the choice to overwrite or rename the files if not set.",
            color="yellow",
        )
        cprint("-----------------------------------------------------", color="cyan")
        cprint(
            "Chain commands together by separating them with a spaced semicolon ( ; ). ie: 'target set <path> ; target output <path>\nUse -o to overwrite the source files when processed. ie: 'process resample 44100 -o'",
            color="yellow",
        )
        cprint("Type 'help' to get a list of available categories.", color="yellow")
        cprint(
            "Type <category> -h to get a list of available commands for that category.",
            color="yellow",
        )
        cprint("Type 'exit' to exit.", color="yellow")
        cprint("-----------------------------------------------------", color="cyan")

        client.parser.interactive()


if __name__ == "__main__":
    main()
