# Streambot

A Discord bot for streaming radio stations and YouTube audio to voice channels.

## Features

- Stream internet radio stations to Discord voice channels
- Play YouTube audio from URLs or search queries
- Queue system for YouTube playback with skip functionality
- Dynamic status display showing currently playing content
- Automatic disconnection when voice channel is empty
- Configuration-driven station management via TOML

## Commands

| Command | Description |
|---------|-------------|
| `/play [station]` | Play a radio station or show selection menu |
| `/play_tags [tags]` | Play a random station matching comma-separated tags |
| `/play_yt [url/query]` | Play YouTube audio from URL or search query |
| `/queue` | Display the current playback queue |
| `/skip` | Skip to the next track in the queue |
| `/stop` | Stop playback and disconnect from voice channel |
| `/list` | List all configured radio stations |
| `/join` | Join your current voice channel |
| `/ping` | Check if the bot is responsive |

## Tech Stack

- **Python 3.12** with async/await patterns
- **discord.py** for Discord API integration
- **yt-dlp** for YouTube audio extraction
- **FFmpeg** for audio streaming and transcoding
- **Pydantic** for configuration validation
- **Docker** for containerized deployment

## Configuration

Radio stations are configured in `radio_stations.toml`:

```toml
[[stations]]
name = "Station Name"
stream_url = "https://example.com/stream"
```

No code changes required to add new stations.

## Running the Bot

### Prerequisites

- Python 3.12 or higher
- FFmpeg installed on your system
- A Discord bot token from the [Discord Developer Portal](https://discord.com/developers/applications)

### Docker (Recommended)

```bash
# Create environment file
echo "DISCORD_TOKEN=your_token_here" > .env

# Build and run
docker build -t streambot .
docker run --env-file .env streambot
```

### Local Development

```bash
# Install uv package manager (https://docs.astral.sh/uv/)
# Then install dependencies
uv sync --all-extras

# Create .env file with your Discord token
echo "DISCORD_TOKEN=your_token_here" > .env

# Run the bot
uv run python app/main.py
```

## Architecture

The bot uses FFmpeg with reconnection settings for reliable radio streaming and yt-dlp for YouTube content. Audio is transcoded to Opus format for Discord compatibility. The queue system maintains per-guild state with automatic retry logic for interrupted playback.

## CI/CD

GitHub Actions workflows handle:
- Linting with Ruff on pull requests
- Docker image builds on main branch pushes
- Automated releases based on VERSION file changes
