r'''
![AudioCLI](https://www.dropbox.com/s/0yjfnabmh8pbjg1/audiocli.png?raw=1)

AudioCLI is an interactive command line tool for audio processing.
After setting target path(s), you send commands to process audio files it recursively finds in those paths.
Appending ```-o``` to a command will overwrite the source files when processed.
You are also able to chain commands together to create a processing pipeline by separating the commands with a spaced semicolon ( ; ).
ie: 
```shell
target set <path> ; target output <path> ; process resample 44100 ; target set <path> ; process mono -o
```
This will:
- Set target folder for files
- Set target output path
- Copy all files to output path and resample to 44.1k
- Re-set target path to previous output
- Overwrite (-o) as mono

Install with:
```shell
pip install git+https://github.com/diontimmer/AudioCLI
```

Launch with:
```shell
audiocli
```

AudioCLI can also be ran as a CLI tool itself straight from the commandline by pre-prending your usual AudioCLI commands with ```audiocli``` ie:
```shell
audiocli process resample 44100
```

Here you can find all the information you need to use the various commands and functions this tool has.
Suggestions and bug reports are welcome on the github page.
Navigate to the core module on the sidebar to get started with the commands this tool has to offer.

# Custom Extensions
AudioCLI is designed to be extended with custom commands and categories. This is done by creating a python module and placing it in the modules/ folder.
Make sure to include a __init__.py file in the module folder to make it a package.

Within your module, you can start defining category files. These are python files that contain a class that inherits from BaseCommandCategory. The category is going to be the first part of the command, so make sure to name it accordingly.
A category can have as many commands as you want, as long as they are defined as a function within the class. Private functions should be prefixed with an underscore ( _ ).
Every command function needs to have proper docstrings to be picked up by the parser, feel free to look at the existing categories for examples.

Every category class needs an overridden _get_info() function that returns a dictionary with the name and description of the category. 
You also have to define the exposed commands in the _get_commands() function. This function should return a dictionary with the command name as key and the function as value.

Have a look at the header of the process category, together with the resample command:
```python
"""
Process target audio paths with various effects.
"""


class ProcessCommands(BaseCommandCategory):
    """
    Process target audio paths with various effects.
    """

    def _get_info(self):
        return {
            "name": "process",
            "description": "Process target paths.",
        }

    # Declare exposed commands
    def _get_commands(self):
        return {
            "resample": self.resample,
            "stereo": self.stereo,
            "mono": self.mono,
            "chunk": self.chunk,
            "bitdepth": self.bitdepth,
        }

    # Define commands

    def resample(self, sample_rate: int):
        """
        Resample all audio files in the current target paths to a new sample rate.

        Args:\n
            sample_rate (int): New sample rate\n
        """
        input_batches = self.client.get_save_paths(f"_resampled_{sample_rate}")

        def resample_batch(args):
            filepath, save_path, _ = args
            audio, sr = load_file(filepath)
            aug_tf = T.Resample(int(sr), int(sample_rate))
            auged = aug_tf(audio)
            save_to_file(save_path, auged, int(sample_rate))

        if input_batches:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.client.batch_size
            ) as executor:
                for batch in tqdm(input_batches, desc="Resampling"):
                    tasks = [
                        (filepath, save_path, sample_rate)
                        for filepath, save_path in zip(*batch)
                    ]
                    executor.map(resample_batch, tasks)
                    ```

'''
