# AudioCLI

![AudioCLI](https://www.dropbox.com/s/0yjfnabmh8pbjg1/audiocli.png?raw=1)

AudioCLI is an interactive command line tool for audio processing.
After setting target path(s), you send commands to process audio files it recursively finds in those paths.
Appending ```-o``` to a command will overwrite the source files when processed.
You are also able to chain commands together to create a processing pipeline by separating the commands with a spaced semicolon ( ; ).
ie: 
```shell
target set <path> ; target output <path> ; process resample 44100; target set <path> ; process mono -o
```
Sets target folder for files -> sets target output path -> copy all files to output path and resample to 44.1k -> Re-set target path to previous output -> overwrite (-o) as mono

Install with:
```shell
pip install git+https://github.com/diontimmer/AudioCLI
```

Documentation can be found [here](https://diontimmer.github.io/AudioCLI/).
