from AudioCLI.src.client import BaseCommandCategory
from termcolor import cprint
import os
import argparse
import os
import concurrent.futures
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
import urllib.parse


class DownloadCommands(BaseCommandCategory):
    # Set command name and description
    """
    Various commands for downloading.
    """

    def _get_info(self):
        return {
            "name": "download",
            "description": "Various commands for downloading.",
        }

    # Declare exposed commands
    def _get_commands(self):
        return {
            "http": self.http,
        }

    def http(self, session, url, recursive=True):
        """
        Download all audio files from an open HTTP directory.

        Args:
            url (str): URL to download from
            recursive (bool): Whether to recursively download from subdirectories
        """
        self._http_download_all(
            session=session,
            url=url,
            output_dir=self.client.output_dir,
            recursive=recursive,
        )

    def _download_audio(self, session, href, url, output_dir, prog):
        audio_url = url + href
        try:
            audio_response = session.get(audio_url)
        except:
            print(f"Connection error for {audio_url}")
            return
        output_path = os.path.join(output_dir, urllib.parse.unquote(href))
        with open(output_path, "wb") as f:
            f.write(audio_response.content)
        prog.update(1)

    def _http_download_all(self, session, url, output_dir, recursive=True):
        session = requests.Session()
        cprint(f"Downloading from {url} to {output_dir}", color="green")
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        try:
            response = session.get(url)
        except:
            cprint(f"Connection error for {url}", color="red")
            return
        soup = BeautifulSoup(response.content, "html.parser")
        raw_links = soup.find_all("a")
        audio_links = [
            link
            for link in raw_links
            if link.get("href").endswith((".wav", ".mp3", ".ogg", ".m4a"))
        ]
        dir_links = [link for link in raw_links if link.get("href").endswith("/")]
        dir_links = [link.get("href") for link in dir_links]
        for link in dir_links:
            if link in url:
                dir_links.remove(link)
        dir_links = list(dict.fromkeys(dir_links))
        dir_links = [url + link for link in dir_links]

        # process

        if audio_links:
            prog = tqdm(total=len(audio_links), initial=0)
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.client.batch_size
            ) as executor:
                for link in audio_links:
                    href = link.get("href")
                    executor.submit(
                        self._download_audio, session, href, url, output_dir, prog
                    )
            prog.close()
        else:
            cprint("No audio files found.", color="red")
        cprint(f"Directory complete!\n", color="green")

        # recursive

        if recursive:
            for directory in dir_links:
                nw_out = urllib.parse.unquote(
                    os.path.join(output_dir + "/" + directory.split("/")[-2])
                )
                self._http_download_all(
                    session=session,
                    url=directory,
                    output_dir=nw_out,
                    recursive=recursive,
                )
