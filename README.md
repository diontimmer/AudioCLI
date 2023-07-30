# AudioCLI

![AudioCLI](https://www.dropbox.com/s/0yjfnabmh8pbjg1/audiocli.png?dl=1)

AudioCLI is an interactive command line tool for audio processing.
After setting target path(s), you send commands to process audio files it recursively finds in those paths.
Appending ```-o``` to a command will overwrite the source files when processed.
You are also able to chain commands together to create a processing pipeline by separating the commands with a spaced semicolon ( ; ).
ie: 
```shell
target set <path> ; target output <path> ; process resample 44100; process mono -o
```

Documentation can be found [here](https://diontimmer.github.io/AudioCLI/).