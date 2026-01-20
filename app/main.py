import asyncio
import logging
import os
import re
import time

import discord
from config import RadioConfig, YTDLSource, known_radio_streams
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from utils import search_radio_station_by_tags

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log"),
    ],
)

logger = logging.getLogger(__name__)

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True


class RadioBot(commands.Bot):
    async def setup_hook(self):
        logger.info("Syncing command tree...")
        await self.tree.sync()
        logger.info("Command tree synced.")


bot = RadioBot(command_prefix="!", intents=intents)

# Dictionary to store queues per guild
guild_queues: dict[int, list[dict]] = {}

# Dictionary to store currently playing track info per guild for retry logic
guild_current_track: dict[int, dict] = {}

try:
    DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
except KeyError as e:
    raise OSError(f"Required environment variable {e} is not set") from e


class RadioSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=radio.name, value=radio.name, description=radio.stream_url[:100]
            )
            for radio in known_radio_streams
        ]
        super().__init__(placeholder="Select a radio station...", options=options)

    async def callback(self, interaction: discord.Interaction):
        # Defer immediately to prevent timeout
        await interaction.response.defer()

        station_name = self.values[0]
        radio_station = next(
            (radio for radio in known_radio_streams if radio.name == station_name), None
        )

        if not radio_station:
            return await interaction.followup.send("Station not found!", ephemeral=True)

        await play_and_notify(interaction, radio_station)


class RadioView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(RadioSelect())


async def get_voice_client(user: discord.Member, guild: discord.Guild) -> discord.VoiceClient:
    if not user.voice or not user.voice.channel:
        raise commands.CommandError("You must be in a voice channel.")

    if guild.voice_client:
        return guild.voice_client  # type: ignore

    logger.info(f"Connecting to voice channel: {user.voice.channel.name}")
    return await user.voice.channel.connect()


async def play_stream(voice_client: discord.VoiceClient, station: RadioConfig):
    if voice_client.is_playing():
        voice_client.stop()

    if not station.stream_url:
        logger.error(f"Station {station.name} has no stream URL")
        return

    logger.info(f"Starting stream: {station.name} ({station.stream_url})")
    try:
        source = await discord.FFmpegOpusAudio.from_probe(
            station.stream_url,
            before_options=station.ffmpeg_options["before_options"],
            options=station.ffmpeg_options["options"],
        )
    except Exception as e:
        logger.error(f"Failed to create audio source: {e}")
        return

    def after_playing(error):
        if error:
            logger.error(f"Player error: {error}")
        else:
            logger.info("Stream finished or stopped.")

    voice_client.play(source, after=after_playing)


async def change_status(bot, radio_station: RadioConfig):
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening, name=radio_station.name
        )
    )


async def play_and_notify(source: discord.Interaction | commands.Context, station: RadioConfig):
    """
    Helper to handle common playback logic:
    1. Check guild/user validity
    2. Get voice client
    3. Play stream
    4. Update status
    5. Notify user
    """
    # Determine user, guild, and send method
    if isinstance(source, discord.Interaction):
        user = source.user
        guild = source.guild
        # Assumes interaction is already deferred if it takes time,
        # or we use followup.
        send_func = source.followup.send
    else:
        user = source.author
        guild = source.guild
        send_func = source.send

    if not isinstance(user, discord.Member) or not guild:
        msg = "You must be in a guild to use this."
        if isinstance(source, discord.Interaction):
            await send_func(msg, ephemeral=True)
        else:
            await send_func(msg)
        return

    try:
        voice_client = await get_voice_client(user, guild)
        await play_stream(voice_client, station)
        await change_status(bot, station)

        logger.info(f"Playing {station.name} requested by {user} in {guild}")
        await send_func(f"Now playing: **{station.name}**\n{station.stream_url}")

    except Exception as e:
        logger.error(f"Failed to play {station.name}: {e}", exc_info=True)
        msg = f"Error: {e}"
        if isinstance(source, discord.Interaction):
            await send_func(msg, ephemeral=True)
        else:
            await send_func(msg)


@bot.hybrid_command(name="ping", description="Check if the bot is alive")
async def ping(ctx):
    await ctx.send("Pong!")


@bot.hybrid_command(name="list", description="List all available radio stations")
async def list_radio_stations(ctx):
    stations = "\n".join(
        [f"{station.name}: {station.stream_url}" for station in known_radio_streams]
    )
    await ctx.send(f"Available stations:\n{stations}")


@bot.hybrid_command(name="join", description="Join the voice channel you are in")
async def join(ctx):
    await ctx.defer()
    try:
        await get_voice_client(ctx.author, ctx.guild)
        await ctx.send(f"Joined {ctx.author.voice.channel}")
    except commands.CommandError as e:
        await ctx.send(str(e))


@bot.hybrid_command(name="play_tags", description="Play a random station matching the given tags")
@app_commands.describe(tags="Comma separated tags to search for (e.g. rock, pop)")
async def play_random_by_tags(ctx, *, tags: str | None = None):
    await ctx.defer()
    if not ctx.guild or not isinstance(ctx.author, discord.Member):
        return await ctx.send("This command can only be used in a server.")

    if tags is None:
        return await ctx.send("Please provide tags to search for radio stations.")

    # Split by comma if present, otherwise by space
    tag_list = tags.split(",") if "," in tags else tags.split()

    try:
        radio_station = await asyncio.to_thread(lambda: search_radio_station_by_tags(tag_list))
    except Exception as e:
        logger.error(f"Error searching for radio station: {e}")
        return await ctx.send(f"Error searching for stations: {e}")

    if not radio_station:
        return await ctx.send(f"No stations found for tags: {tags}")

    await play_and_notify(ctx, radio_station)


@bot.hybrid_command(name="play", description="Play a specific radio station")
@app_commands.describe(station="Name of the station to play")
async def play_radio(ctx, station: str | None = None):
    await ctx.defer()
    if not ctx.guild or not isinstance(ctx.author, discord.Member):
        return await ctx.send("This command can only be used in a server.")

    if station is None:
        return await ctx.send("Select a radio station:", view=RadioView())

    radio_station = next(
        (radio for radio in known_radio_streams if radio.name.lower() == station.lower()), None
    )

    if not radio_station:
        available = ", ".join(r.name for r in known_radio_streams)
        return await ctx.send(f"Unknown station '{station}'. Available: {available}")

    await play_and_notify(ctx, radio_station)


@bot.hybrid_command(name="stop", description="Stop playing and disconnect")
async def stop(ctx):
    if not ctx.guild:
        return await ctx.send("This command can only be used in a server.")

    if ctx.guild.voice_client:
        # Clear queue and current track info
        guild_id = ctx.guild.id
        if guild_id in guild_queues:
            guild_queues[guild_id].clear()
        if guild_id in guild_current_track:
            del guild_current_track[guild_id]

        await bot.change_presence(activity=None)
        await ctx.guild.voice_client.disconnect()
        await ctx.send("Disconnected from voice channel.")
    else:
        await ctx.send("Not connected to a voice channel.")


@bot.hybrid_command(name="skip", description="Skip to the next song in the queue")
async def skip(ctx):
    if not ctx.guild:
        return await ctx.send("This command can only be used in a server.")

    voice_client = ctx.guild.voice_client
    if not voice_client or not voice_client.is_playing():
        return await ctx.send("Nothing is playing right now.")

    guild_id = ctx.guild.id
    queue_length = len(guild_queues.get(guild_id, []))

    if queue_length > 0:
        await ctx.send(f"Skipping to next song... ({queue_length} songs left in queue)")
    else:
        await ctx.send("Skipping current song... (no more songs in queue)")

    # Stop the current song, which will trigger the after_playing callback
    # and automatically play the next song in the queue
    voice_client.stop()


async def play_next_in_queue(guild: discord.Guild, voice_client: discord.VoiceClient):
    """Check queue and play next item if available"""
    guild_id = guild.id

    if guild_id not in guild_queues or not guild_queues[guild_id]:
        # Queue is empty, clear status
        await bot.change_presence(activity=None)
        logger.info(f"Queue finished for guild {guild.name}")
        return

    # Get next item from queue
    next_item = guild_queues[guild_id].pop(0)
    url = next_item["url"]

    logger.info(f"Playing next in queue for {guild.name}: {url}")

    try:
        await play_youtube_url(voice_client, url, guild)
    except Exception as e:
        logger.error(f"Error playing next in queue: {e}")
        # Try to play the next one
        await play_next_in_queue(guild, voice_client)


async def play_youtube_url(
    voice_client: discord.VoiceClient, url: str, guild: discord.Guild, retry_count: int = 0
):
    """Play a YouTube URL and set up queue handling"""
    guild_id = guild.id

    try:
        player = await YTDLSource.from_url(url, loop=bot.loop, stream=True)
    except Exception as e:
        logger.error(f"Failed to fetch stream info: {e}")
        # If this fails, move to next song
        await play_next_in_queue(guild, voice_client)
        raise

    # Store current track info for potential retry
    guild_current_track[guild_id] = {
        "url": url,
        "title": player.title,
        "start_time": time.time(),
        "retry_count": retry_count,
    }

    def after_playing(error):
        if error:
            logger.error(f"Player error: {error}")

        # Check if playback ended prematurely (within 10 seconds suggests a connection error)
        current_time = time.time()
        track_info = guild_current_track.get(guild_id)

        if track_info:
            elapsed = current_time - track_info["start_time"]

            # If song played for less than 10 seconds and we haven't retried too many times, retry
            if elapsed < 10 and track_info["retry_count"] < 3:
                logger.warning(
                    f"Playback ended prematurely after {elapsed:.1f}s. "
                    f"Retrying (attempt {track_info['retry_count'] + 1}/3)..."
                )
                next_retry = track_info["retry_count"] + 1
                asyncio.run_coroutine_threadsafe(
                    play_youtube_url(voice_client, track_info["url"], guild, next_retry),
                    bot.loop,
                )
                return

        # Normal completion or max retries reached - play next in queue
        asyncio.run_coroutine_threadsafe(play_next_in_queue(guild, voice_client), bot.loop)

    voice_client.play(player, after=after_playing)

    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.listening, name=player.title)
    )

    return player  # Return so we can get the title


def is_url(text: str) -> bool:
    """Check if the provided text is a URL"""
    url_pattern = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|m\.youtube\.com)/.+$", re.IGNORECASE
    )
    return bool(url_pattern.match(text))


@bot.hybrid_command(name="queue", description="Show the current queue")
async def show_queue(ctx):
    if not ctx.guild:
        return await ctx.send("This command can only be used in a server.")

    guild_id = ctx.guild.id

    # Check what's currently playing
    voice_client = ctx.guild.voice_client
    current_song = None
    if voice_client and voice_client.is_playing():
        current_song = "Currently playing"

    if guild_id not in guild_queues or not guild_queues[guild_id]:
        if current_song:
            return await ctx.send(f"{current_song}\n\nQueue is empty!")
        return await ctx.send("Queue is empty and nothing is playing!")

    queue_items = []
    for i, item in enumerate(guild_queues[guild_id]):
        if is_url(item["url"]):
            url_display = item["url"]
        else:
            url_display = item["url"].replace("ytsearch:", "Search: ")
        queue_items.append(f"{i + 1}. {url_display} (requested by {item['requester'].name})")

    queue_list = "\n".join(queue_items)

    message = ""
    if current_song:
        message += f"{current_song}\n\n"
    message += f"**Queue ({len(guild_queues[guild_id])} songs):**\n{queue_list}"

    await ctx.send(message)


@bot.hybrid_command(name="play_yt", description="Play audio from a YouTube URL")
@app_commands.describe(query="YouTube URL or search query to play")
async def play_yt(ctx, *, query: str):
    await ctx.defer()
    if not ctx.guild or not isinstance(ctx.author, discord.Member):
        return await ctx.send("This command can only be used in a server.")

    guild_id = ctx.guild.id

    # Initialize queue for this guild if it doesn't exist
    if guild_id not in guild_queues:
        guild_queues[guild_id] = []

    try:
        voice_client = await get_voice_client(ctx.author, ctx.guild)

        if not is_url(query):
            # Search YouTube for the query and get the first result URL
            search_query = f"ytsearch:{query}"
            await ctx.send(f"Searching for: **{query}**...")
        else:
            search_query = query

        # If something is already playing, add to queue
        if voice_client.is_playing():
            guild_queues[guild_id].append({"url": search_query, "requester": ctx.author})

            position_msg = f"Added to queue at position {len(guild_queues[guild_id])}"
            if not is_url(query):
                position_msg += f"\nSearch: **{query}**"

            await ctx.send(position_msg)
            return

        player = await play_youtube_url(voice_client, search_query, ctx.guild)
        await ctx.send(f"Now playing: **{player.title}**")

    except Exception as e:
        logger.error(f"Error playing YouTube URL: {e}", exc_info=True)
        await ctx.send(f"An error occurred: {e}")


@bot.event
async def on_voice_state_update(member, before, after):
    # Check if the bot is connected to a voice channel in this guild
    if not member.guild.voice_client:
        return

    # Check if the user left the channel the bot is currently in
    if before.channel and before.channel == member.guild.voice_client.channel:
        # Count members in the channel (excluding bots)
        members = [m for m in before.channel.members if not m.bot]

        if not members:
            logger.info(f"No users left in {before.channel.name}, disconnecting...")
            # Clear queue and current track info
            guild_id = member.guild.id
            if guild_id in guild_queues:
                guild_queues[guild_id].clear()
            if guild_id in guild_current_track:
                del guild_current_track[guild_id]

            await bot.change_presence(activity=None)
            await member.guild.voice_client.disconnect()


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
