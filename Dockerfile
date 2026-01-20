FROM python:3.12-slim-bookworm

# Install system dependencies
# ffmpeg is required for audio streaming
# libffi-dev and python3-dev are needed for building python extensions
# libsodium-dev is required for PyNaCl (voice support)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libffi-dev \
    python3-dev \
    libsodium-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Copy dependency definitions
COPY pyproject.toml uv.lock* ./

# Install dependencies
# We use --no-dev to exclude development dependencies
RUN uv sync --no-dev --no-install-project

# Copy the rest of the application
COPY . .

# Run the application
CMD ["uv", "run", "python", "app/main.py"]
