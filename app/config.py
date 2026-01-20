import asyncio
import tomllib
from pathlib import Path

import discord
import yt_dlp
from pydantic import BaseModel, Field
from yt_dlp import YoutubeDL

default_ffmpeg_options = {
    "before_options": (
        "-reconnect 1 "
        "-reconnect_streamed 1 "
        "-reconnect_delay_max 5 "
        "-reconnect_on_network_error 1 "
        "-reconnect_on_http_error 4xx,5xx "
        "-rw_timeout 5000000 "
        "-nostdin "
        "-hide_banner "
        "-user_agent 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36' "
        "-analyzeduration 10M "
        "-probesize 10M "
        "-thread_queue_size 4096 "
        "-loglevel warning "
        "-err_detect ignore_err "
        "-fflags +discardcorrupt "
    ),
    "options": (
        "-vn "
        "-acodec libopus "
        "-ar 48000 "
        "-ac 2 "
        "-b:a 96k "
        "-application audio "
        "-packet_loss 15 "
        "-fec 1 "
        "-vbr on "
        "-compression_level 0 "
        "-frame_duration 20 "
        "-bufsize 8M "
        "-avoid_negative_ts make_zero "
        "-fflags +genpts+igndts "
        "-max_muxing_queue_size 9999 "
        "-af asetpts=PTS-STARTPTS,volume=1.0 "
    ),
}

yt_dlp_format_options: dict = {
    "format": "bestaudio[abr>=128]/bestaudio/best",  # Prefer higher bitrate audio
    "outtmpl": "%(extractor)s-%(id)s-%(title)s.%(ext)s",
    "restrictfilenames": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",  # bind to ipv4 since ipv6 addresses cause issues sometimes
}

ytdl = yt_dlp.YoutubeDL(yt_dlp_format_options)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)

        self.data = data

        self.title = data.get("title")
        self.url = data.get("url")
        self.duration = data.get("duration")

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False, ytdl_client: YoutubeDL = ytdl):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, lambda: ytdl_client.extract_info(url, download=not stream)
        )

        if "entries" in data:
            # Handle playlists and search results - take first item
            if not data["entries"]:
                raise ValueError("No results found")
            data = data["entries"][0]

        filename = data.get("url") if stream else ytdl_client.prepare_filename(data)

        if not filename:
            raise ValueError("Could not retrieve filename or URL")

        # Use FFmpegPCMAudio with enhanced options for better audio quality
        # PCMVolumeTransformer requires non-Opus encoded audio
        return cls(
            discord.FFmpegPCMAudio(
                filename,
                before_options=(
                    "-reconnect 1 "
                    "-reconnect_streamed 1 "
                    "-reconnect_delay_max 5 "
                    "-nostdin "
                    "-probesize 10M "
                    "-analyzeduration 10M"
                ),
                options=("-vn -b:a 128k -ar 48000 -ac 2 -bufsize 512k -async 1"),
            ),
            data=data,
        )


class RadioConfig(BaseModel):
    name: str
    stream_url: str
    ffmpeg_options: dict[str, str] = Field(default_factory=lambda: default_ffmpeg_options)


def load_radio_stations(config_path: str = "radio_stations.toml") -> list[RadioConfig]:
    """Load radio stations from TOML configuration file."""
    # Try to find the config file in multiple locations
    possible_paths = [
        Path(config_path),  # Current directory
        Path(__file__).parent.parent / config_path,  # Project root
    ]

    config_file = None
    for path in possible_paths:
        if path.exists():
            config_file = path
            break

    if not config_file:
        raise FileNotFoundError(
            f"Could not find {config_path}. Searched in: {[str(p) for p in possible_paths]}"
        )

    with open(config_file, "rb") as f:
        data = tomllib.load(f)

    stations = []
    for station_data in data.get("stations", []):
        stations.append(
            RadioConfig(
                name=station_data["name"],
                stream_url=station_data["stream_url"],
            )
        )

    return stations


known_radio_streams: list[RadioConfig] = load_radio_stations()
