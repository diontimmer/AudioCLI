from .target_data import TargetData
import icli
from termcolor import cprint
import inspect


class BaseCommandCategory:
    def __init__(self, main_parser, client):
        self.client = client
        self.name = self.get_info()["name"]
        self.description = self.get_info()["description"]
        self.main_parser = main_parser
        self.cat_parser = main_parser.add_parser(self.name, help=self.description)
        self.subparsers = self.cat_parser.add_subparsers(
            dest="_command", metavar="command", help="Command"
        )

        for command_name, function in self.get_commands().items():
            self._create_command_parser(command_name, function)

    def get_info(self):
        return {
            "name": "default",
            "description": "default",
        }

    def get_commands(self):
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
            help_text = (
                type.__doc__ if type and type.__doc__ else "No help text available"
            )
            nargs = "+" if type == list else None
            command_parser.add_argument(
                arg, nargs=nargs, default=default, help=help_text
            )

    def my_command(self, arg1: int, arg2: str = "default"):
        """
        This is my_command. It does something amazing.

        Args:
            arg1 (int): This is the first argument. It should be an integer.
            arg2 (str, optional): This is the second argument. It's a string and is optional.
        """
        pass


class InteractiveClient(icli.ArgumentParser):
    def __init__(self, *args, **kwargs):
        self.target_data = TargetData()
        self.output_dir = None  # Store the output directory
        self.batch_size = 3  # Store the batch size, default is 3
        self.categories = {}
        super().__init__(*args, **kwargs)

    def run(self, _category, _command=None, **kwargs):
        try:
            for category_name, category in self.categories.items():
                if _category == category.name:
                    if _command in category.get_commands().keys():
                        func = category.get_commands()[_command]
                        func(**kwargs)
                    else:
                        cprint(
                            f"Error: command {_command} does not exist for category {_category}.",
                            color="red",
                        )
                    return
            cprint(f"Error: category {_category} does not exist.", color="red")
        except Exception as e:
            cprint(f"Error: {e}", color="red")
