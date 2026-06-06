FROM python:3.11-slim

WORKDIR /app

COPY . .

# Install Node.js (JavaScript runtime for yt-dlp) and ffmpeg
RUN apt-get update && apt-get install -y \
    nodejs \
    npm \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "-m", "bot.main"]
