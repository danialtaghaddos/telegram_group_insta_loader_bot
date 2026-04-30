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

def compress_video(input_path: str) -> str:
    if not input_path.lower().endswith((".mp4", ".mov")):
        return input_path

    output_path = os.path.splitext(input_path)[0] + "_ios.mp4"
    vf = "scale='min(720,iw)':-2:force_original_aspect_ratio=decrease"

    cmd = [
        "ffmpeg", "-i", input_path,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "32",                    # Higher CRF = smaller size
        "-c:a", "aac",
        "-b:a", "96k",
        "-pix_fmt", "yuv420p",
        "-vf", "scale='min(720,iw)':-2:force_original_aspect_ratio=decrease",
        "-movflags", "+faststart",
        "-threads", "2",
        "-y",
        output_path
    ]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=90)
        logger.info(f"✅ iOS re-encode succeeded: {output_path}")
        if os.path.exists(input_path) and input_path != output_path:
            os.unlink(input_path)
        return output_path
    except subprocess.TimeoutExpired:
        logger.warning(f"ffmpeg timeout - skipping re-encode for {input_path}")
        return input_path
    except Exception as e:
        logger.error(f"ffmpeg re-encode failed: {e}")
        return input_path

