from .target_data import TargetData
import icli
from termcolor import cprint
import inspect
import torch
import traceback
import sys
import pkgutil
import importlib
import os
from AudioCLI.src.util import chunks, extract_arg_help
import json

_REPEAT_ONCE = 1
_REPEAT_CONT = 2
_REPEAT_CONT_CLS = 3

FILE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class BaseCommandCategory:
    def __init__(self, main_parser, client):
        self.client = client
        self.name = self._get_info()["name"]
        self.description = self._get_info()["description"]
        self.main_parser = main_parser
        self.cat_parser = main_parser.add_parser(self.name, help=self.description)
        self.subparsers = self.cat_parser.add_subparsers(
            dest="_command",
            metavar="command",
            help="(<category> <command> -h for more info.)",
        )

        for command_name, function in self._get_commands().items():
            self._create_command_parser(command_name, function)

    def _get_info(self):
        return {
            "name": "default",
            "description": "default",
        }

    def _get_commands(self):
        return {}

    def _create_command_parser(self, command_name, function):
        args = inspect.getfullargspec(function)
        command_parser = self.subparsers.add_parser(
            command_name,
            help=function.__doc__
            if function.__doc__
            else "No help text available",  # use function docstring as command help text
        )

        defaults = (
            dict(zip(args.args[-len(args.defaults) :], args.defaults))
            if args.defaults
            else {}
        )

        for arg in args.args:
            # skip if arg is self
            if arg == "self":
                continue

            default = defaults.get(arg, None)
            type = args.annotations.get(arg, None)
            help_text = extract_arg_help(arg, function.__doc__)

            if type == bool:
                if default is None:  # Required argument
                    default = False
                    action = "store_true"
                else:
                    default = bool(default)  # Ensure default is a boolean
                    action = "store_true" if not default else "store_false"

                arg_key = f"--{arg.replace('_', '-')}"

                command_parser.add_argument(
                    arg_key,
                    default=default,
                    help=help_text,
                    action=action,
                )

            else:
                nargs = "+" if type == list else None
                action = "store"

                if default is None:  # If no default value, create a positional argument
                    command_parser.add_argument(
                        arg,
                        nargs=nargs,
                        help=help_text,
                        action=action,
                    )
                else:  # If a default value exists, create an optional argument
                    arg_key = f"--{arg.replace('_', '-')}"
                    command_parser.add_argument(
                        arg_key,
                        nargs=nargs,
                        default=default,
                        help=help_text,
                        action=action,
                    )

        # add args for -o
        command_parser.add_argument(
            "-o",
            action="store_true",
            default=False,
            help="Overwrite source file.",
        )


class InteractiveClient:
    def __init__(self, *args, **kwargs):
        self.target_data = TargetData()
        self.output_dir = None
        self.batch_size = 3
        self.parser = InteractiveParser(
            prog="" if len(sys.argv) < 2 else None, client=self
        )
        self.categories = self.load_categories("AudioCLI.modules")
        self.device = self.detect_device()
        self.overwrite_mode = None
        super().__init__(*args, **kwargs)

    def load_from_settings(self):
        json_path = os.path.join(FILE_DIR, "last_settings.json")
        if os.path.exists(json_path):
            with open(json_path, "r") as f:
                settings = json.load(f)
            self.target_data.from_settings(settings)
            self.output_dir = settings["output_dir"]
            self.batch_size = settings["batch_size"]
            self.device = torch.device(settings["device"])
            cprint("Loaded settings from last session.", color="green")

    def save_to_settings(self):
        json_path = os.path.join(FILE_DIR, "last_settings.json")
        settings = {}
        settings["search_paths"] = self.target_data.search_paths
        settings["output_dir"] = self.output_dir
        settings["batch_size"] = self.batch_size
        settings["device"] = str(self.device)
        open(json_path, "w").write(json.dumps(settings, indent=4))

    def get_save_paths(self, id_str):
        output_overwrite = False
        if not self.target_data.contains_data():
            cprint("No data loaded.", color="red")
            return None
        if self.overwrite_mode == "o":
            output_overwrite = True
        batches = []
        chunked = chunks(self.target_data.file_paths, self.batch_size)
        for fp_batch in chunked:
            save_paths = []
            for file_path in fp_batch:
                if output_overwrite:
                    save_path = file_path
                else:
                    if self.output_dir is None:
                        save_path = (
                            os.path.splitext(file_path)[0]
                            + id_str
                            + os.path.splitext(file_path)[1]
                        )
                    else:
                        save_path = os.path.join(
                            self.output_dir, os.path.basename(file_path)
                        )
                        save_path = (
                            os.path.splitext(save_path)[0]
                            + id_str
                            + os.path.splitext(save_path)[1]
                        )
                save_paths.append(save_path)

            batches.append((fp_batch, save_paths))

        return batches

    def detect_device(self, print=True):
        if torch.cuda.is_available():
            device = torch.device("cuda")
        else:
            device = torch.device("cpu")
        self.device = device
        if print:
            if self.device != "cpu":
                cprint(
                    f"Using device {self.device}",
                    color="green",
                )

            else:
                cprint(
                    "No CUDA/MPS Detected! Using CPU, change using: 'target device <device>'",
                    color="orange",
                )
        return device

    def load_categories(self, package_name):
        categories = {}

        def load_module(module, sp):
            # iterate over all objects in the module
            for obj_name in dir(module):
                obj = getattr(module, obj_name)

                # check if object is a class and is a subclass of BaseCommandCategory
                if (
                    isinstance(obj, type)
                    and issubclass(obj, BaseCommandCategory)
                    and obj != BaseCommandCategory
                ):
                    instance = obj(
                        main_parser=sp, client=self
                    )  # instantiate the class]
                    categories[obj.__name__] = instance

        def load_package(package, sp):
            # iterate over all modules and packages in the package
            for _, module_name, is_pkg in pkgutil.iter_modules(package.__path__):
                full_name = f"{package.__name__}.{module_name}"
                if is_pkg:
                    load_package(importlib.import_module(full_name), sp)
                else:
                    load_module(importlib.import_module(full_name), sp)

        sp = self.parser.add_subparsers(
            dest="_category", metavar="category", help="(<category> -h for more info.)"
        )

        load_package(importlib.import_module(package_name), sp)

        self.parser.categories = categories

        return categories


class InteractiveParser(icli.ArgumentParser):
    def __init__(self, *args, **kwargs):
        self.client = kwargs.pop("client", None)
        super().__init__(*args, **kwargs)

    def run(self, _category, _command=None, **kwargs):
        o = kwargs.pop("o", False)
        if o:
            self.client.overwrite_mode = "o"
        else:
            self.client.overwrite_mode = None
        try:
            for category_name, category in self.client.categories.items():
                if _category == category.name:
                    if _command in category._get_commands().keys():
                        func = category._get_commands()[_command]
                        self.client.target_data.scan(
                            self.client.target_data.search_paths
                        )
                        func(**kwargs)
                        self.client.save_to_settings()
                        if self.client.target_data.contains_data():
                            self.client.target_data.scan(
                                self.client.target_data.search_paths
                            )
                            cprint(
                                f"Current target paths: {self.client.target_data.search_paths} | ({len(self.client.target_data.file_paths)}) files",
                                color="green",
                            )
                        return
                    else:
                        if _command:
                            cprint(
                                f"Error: command {_command} does not exist for category {_category}.",
                                color="red",
                            )
                        else:
                            cprint(
                                f"Error: command not specified for category {_category}. Type {_category} -h for more info.",
                                color="red",
                            )
            cprint(f"Error: category {_category} does not exist.", color="red")
        except Exception as e:
            cprint(f"Error: {e}", color="red")
            traceback.print_exc()

    def get_interactive_prompt(self):
        if self.current_section:
            ps = "/".join(self.current_section) + "> "
        else:
            ps = "AudioCLI> "
        return ps

    def _print_message(self, message, file=None):
        if message:
            try:
                cprint(message, color="yellow")
            except (AttributeError, OSError):
                pass

    def interactive(self, stream=None):
        import readline
        import argcomplete
        import shlex
        import time
        import os
        import sys

        def save_history():
            if self.interactive_history_file:
                try:
                    readline.write_history_file(
                        os.path.expanduser(self.interactive_history_file)
                    )
                except:
                    pass

        if stream:
            input_strings = stream.readlines()
            if not input_strings:
                return
            sidx = 0
        else:
            self._i_completer = argcomplete.CompletionFinder(
                self, default_completer=argcomplete.completers.SuppressCompleter()
            )
            readline.set_completer_delims("")
            readline.set_history_length(self.interactive_history_length)
            if self.interactive_history_file:
                try:
                    readline.read_history_file(
                        os.path.expanduser(self.interactive_history_file)
                    )
                except:
                    pass
        while True:
            try:
                if stream:
                    try:
                        input_str = input_strings[sidx]
                    except IndexError:
                        return
                    if sidx:
                        print()
                    sidx += 1
                else:
                    input_str = input(self.get_interactive_prompt())
                try:
                    input_arr = shlex.split(input_str)
                except:
                    print("invalid input", file=sys.stderr)
                    input_arr = None
                if not input_arr:
                    continue
                if input_arr[-1].startswith("|"):
                    repeat = input_arr.pop()[1:]
                    if repeat.startswith("c"):
                        do_repeat = _REPEAT_CONT_CLS
                        repeat = repeat[1:]
                    else:
                        do_repeat = _REPEAT_CONT
                    try:
                        repeat_seconds = float(repeat)
                    except:
                        self.handle_interactive_exception()
                        continue
                else:
                    do_repeat = _REPEAT_ONCE
                if ";" in input_arr:
                    size = len(input_arr)
                    idx_list = [
                        idx + 1 for idx, val in enumerate(input_arr) if val == ";"
                    ]
                    input_val = [
                        input_arr[i:j]
                        for i, j in zip(
                            [0] + idx_list,
                            idx_list + ([size] if idx_list[-1] != size else []),
                        )
                    ]
                else:
                    input_val = [input_arr]
                if do_repeat == _REPEAT_CONT_CLS:
                    input_str = " ".join(input_arr)
                    self.clear_screen()
                    self.print_repeat_title(input_str, repeat_seconds)
                while do_repeat:
                    if do_repeat == _REPEAT_ONCE:
                        do_repeat = 0
                    for pidx, parsed in enumerate(input_val):
                        parsed = parsed.copy()
                        if parsed[-1] == ";":
                            parsed.pop()
                        if not parsed:
                            continue
                        if len(parsed) == 1:
                            if parsed[0] == "/":
                                self.current_section = []
                                continue
                            elif parsed[0] == "..":
                                try:
                                    self.current_section.pop()
                                except IndexError:
                                    pass
                                continue
                            elif parsed[0] in self.interactive_help:
                                self.print_global_help()
                                parsed[0] = "-h"
                            elif parsed[0] in self.interactive_quit:
                                if not stream:
                                    save_history()
                                print()
                                return
                        # try to jump to section
                        jump_to = []
                        sect = self.sections
                        if parsed[0] in self.interactive_global_commands:
                            try:
                                self.interactive_global_commands[parsed[0]](*parsed)
                            except:
                                self.handle_interactive_exception()
                            continue
                        if parsed[0].startswith("/"):
                            root_cmd = True
                            parsed[0] = parsed[0][1:]
                        else:
                            root_cmd = False
                            for i in self.current_section:
                                try:
                                    sect = sect[i]
                                except TypeError:
                                    break
                        for p in parsed:
                            if sect and p in sect:
                                jump_to.append(p)
                            else:
                                jump_to = None
                                break
                            try:
                                sect = sect[p]
                            except TypeError:
                                sect = None
                        if jump_to:
                            if root_cmd:
                                self.current_section = jump_to
                            else:
                                self.current_section += jump_to
                            continue
                        if not root_cmd and self.current_section:
                            if len(parsed) == 1 and parsed[0] == "-h":
                                args = self.current_section + parsed
                            else:
                                args = []
                                cs_added = False
                                for p in parsed:
                                    if not p.startswith("-") and not cs_added:
                                        cs_added = True
                                        if not p.startswith("/"):
                                            args += self.current_section
                                        else:
                                            args.append(p[1:])
                                            continue
                                    args.append(p)
                        else:
                            args = parsed
                        try:
                            a = self.parse_args(args)
                        except:
                            self.handle_interactive_parser_exception()
                            continue
                        try:
                            if self.send_args_as_dict:
                                self.run(**a.__dict__)
                            else:
                                self.run(a)
                        except:
                            self.handle_interactive_exception()
                        if pidx < len(input_val) - 1:
                            print()
                    if do_repeat:
                        time.sleep(repeat_seconds)
                        if do_repeat == _REPEAT_CONT_CLS:
                            self.clear_screen()
                            self.print_repeat_title(input_str, repeat_seconds)
                        else:
                            print()
            except KeyboardInterrupt:
                print()
                exit()
            except EOFError:
                if self.current_section:
                    self.current_section.pop()
                    print()
                    continue
                else:
                    save_history()
                    print()
                    return
