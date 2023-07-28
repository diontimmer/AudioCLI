from src.client import InteractiveClient, BaseCommandCategory
from termcolor import cprint
import sys
import pkgutil
import importlib
import os


def load_categories(package_name, client):
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
                instance = obj(main_parser=sp, client=client)  # instantiate the class
                categories[obj.__name__] = instance

    def load_package(package, sp):
        # iterate over all modules and packages in the package
        for _, module_name, is_pkg in pkgutil.iter_modules(package.__path__):
            full_name = f"{package.__name__}.{module_name}"
            if is_pkg:
                load_package(importlib.import_module(full_name), sp)
            else:
                load_module(importlib.import_module(full_name), sp)

    sp = client.add_subparsers(dest="_category", metavar="category", help="Commands")

    load_package(importlib.import_module(package_name), sp)

    return categories


def main():
    # get file path
    client = InteractiveClient(prog="" if len(sys.argv) < 2 else None)
    categories = load_categories("modules", client)

    client.categories = categories

    if len(sys.argv) > 1:
        client.launch()
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
            "Please set your output folder by typing 'target output <path>'. You will be presented the choice to overwrite or rename the files if not set.",
            color="green",
        )
        cprint("-----------------------------------------------------", color="green")
        print()
        client.interactive()


if __name__ == "__main__":
    main()
