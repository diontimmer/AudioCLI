from setuptools import setup, find_packages

setup(
    name="AudioCLI",
    version="0.1",
    packages=find_packages(),
    url="https://github.com/diontimmer/AudioCLI",
    author="Dion Timmer",
    author_email="diontimmer@live.nl",
    description="An interactive command line tool for audio processing.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    entry_points={
        "console_scripts": [
            "audiocli=AudioCLI.AudioCLI:main",
        ],
    },
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
    ],
    install_requires=[
        "torch",
        "torchaudio",
        "pdoc",
        "aeiou",
        "icli",
        "pedalboard",
        "einops",
        "termcolor",
        "bs4",
    ],
)
