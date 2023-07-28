from src.client import InteractiveClient
from termcolor import cprint
import sys


def main():
    ap = InteractiveClient(prog="" if len(sys.argv) < 2 else None)

    sp = ap.add_subparsers(dest="_cmd", metavar="cmd", help="Core Commands")

    # Add the "target" command
    ap_target = sp.add_parser("target", help="Set target paths")
    ap_target_subparsers = ap_target.add_subparsers(
        dest="_command", metavar="command", help="Command"
    )
    ap_target_set = ap_target_subparsers.add_parser("set", help="Set target paths")
    ap_target_set.add_argument(
        "paths", nargs="+", metavar="PATH", help="Paths to target"
    )

    ap_target_info = ap_target_subparsers.add_parser(
        "info", help="Show target information"
    )

    # Add the "batch_size" command
    ap_batch_size = sp.add_parser("batch_size", help="Set batch size")
    ap_batch_size_subparsers = ap_batch_size.add_subparsers(
        dest="_command", metavar="command", help="Command"
    )
    ap_batch_size_set = ap_batch_size_subparsers.add_parser(
        "set", help="Set batch size"
    )
    ap_batch_size_set.add_argument("size", type=int, help="Batch size to set")

    # Add the "output" command
    ap_output = sp.add_parser("output", help="Set output directory")
    ap_output_subparsers = ap_output.add_subparsers(
        dest="_command", metavar="command", help="Command"
    )
    ap_output_set = ap_output_subparsers.add_parser("set", help="Set output directory")
    ap_output_set.add_argument("dir", metavar="DIR", help="Directory to write output")

    # Add the "process" command
    ap_process = sp.add_parser("process", help="Process targets")
    ap_process_subparsers = ap_process.add_subparsers(
        dest="_command", metavar="command", help="Command"
    )

    # Add resample subcommand
    ap_resample = ap_process_subparsers.add_parser(
        "resample", help="Resample audio files"
    )
    ap_resample.add_argument("sample_rate", type=int, help="Sample rate to resample to")

    # Add other subcommand
    ap_other = ap_process_subparsers.add_parser(
        "other_command", help="Other audio processing command"
    )
    ap_other.add_argument("param1", help="First parameter")
    ap_other.add_argument("param2", help="Second parameter")

    ap.interactive_history_file = ".acli_history"

    if len(sys.argv) > 1:
        ap.launch()
    else:
        cprint(
            "Welcome to AudioCLI! Augmenting in batch | By Dion Timmer", color="green"
        )
        cprint("-----------------------------------------------------", color="green")
        cprint(
            "Please set your target folder(s) by typing 'target set <path>, <path>, <path>'. Multiple are optional.",
            color="green",
        )
        cprint(
            "Please set your output folder by typing 'output set <path>'. You will be presented the choice to overwrite or rename the files if not set.",
            color="green",
        )
        cprint("-----------------------------------------------------", color="green")
        print()
        ap.interactive()


if __name__ == "__main__":
    main()
