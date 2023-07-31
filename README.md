# AudioCLI

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

Documentation can be found [here](https://diontimmer.github.io/AudioCLI/).

Some of the functions include:
- Resampling.
- Pitching.
- Chunking to specific length.
- Remove files under silence threshold.
- Batch change bitrate.
- Multithreaded processing.
- Multiformat support.
- Export as .pt (pytorch) files.
- Run commands from .acli file. (process file ./acli_file.acli)
- Command chaining.
- Custom function hook support. (process hook {file} {function})
- Scrape open HTTP directory for audio files.
