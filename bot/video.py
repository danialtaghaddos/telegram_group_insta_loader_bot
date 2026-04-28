# bot/video.py
import subprocess, os
from .config import logger

def get_video_metadata(file_path: str):
    """Use ffprobe to get width, height, and duration"""
    try:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-select_streams", "v:0", "-show_entries",
            "stream=width,height,duration", file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        import json
        data = json.loads(result.stdout)
        
        stream = data.get("streams", [{}])[0]
        width = stream.get("width", 720)
        height = stream.get("height", 1280)
        duration = int(float(stream.get("duration", 0))) if stream.get("duration") else 0
        
        return width, height, duration
    except Exception as e:
        logger.warning(f"Failed to get metadata for {file_path}: {e}")
        return 720, 1280, 0  # safe defaults for vertical video