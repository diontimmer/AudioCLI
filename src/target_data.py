from aeiou.core import fast_scandir


class TargetData:
    def __init__(self):
        self.search_paths = []
        self.file_paths = []

    def contains_data(self):
        return self.file_paths

    def scan(self, search_paths):
        self.search_paths = search_paths
        self.file_paths = []
        for path in search_paths:
            _, files = fast_scandir(path, [".mp3", ".wav", ".ogg", ".flac"])
            self.file_paths.extend(files)
        return len(self.file_paths)
