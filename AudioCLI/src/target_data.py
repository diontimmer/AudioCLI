from aeiou.core import fast_scandir
import os


class TargetData:
    def __init__(self):
        self.search_paths = []
        self.file_paths = []

    def contains_data(self):
        return self.file_paths

    def scan(self, search_paths, recursive=True):
        self.search_paths = search_paths
        self.file_paths = []
        exts = [".mp3", ".wav", ".ogg", ".flac"]
        for path in search_paths:
            if recursive:
                _, files = fast_scandir(path, exts)
            else:
                # get all audio files in the directory
                files = [
                    os.path.join(path, f)
                    for f in os.listdir(path)
                    if os.path.isfile(os.path.join(path, f))
                    and os.path.splitext(f)[1].lower() in exts
                ]
            self.file_paths.extend(files)
        return len(self.file_paths)

    def from_settings(self, settings):
        self.search_paths = settings["search_paths"]
        self.scan(self.search_paths)
