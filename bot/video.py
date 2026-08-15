# bot/video.py
import subprocess, os
from .config import logger

def _video_codec(file_path: str) -> str | None:
    """Return the video stream's codec name (e.g. "h264", "vp9", "av1"), or
    None if it can't be determined."""
    try:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-select_streams", "v:0", "-show_entries",
            "stream=codec_name", file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        import json
        data = json.loads(result.stdout)
        return data.get("streams", [{}])[0].get("codec_name")
    except Exception as e:
        logger.warning(f"Failed to probe codec for {file_path}: {e}")
        return None


# Codecs Telegram's client-side player can reliably decode. Anything else
# (commonly VP9/AV1, which yt-dlp's "best" format pick tends to prefer,
# especially with no height cap) plays audio over a black frame instead of
# erroring out, so it needs a real re-encode rather than a stream copy.
TELEGRAM_COMPATIBLE_VIDEO_CODECS = {"h264", "hevc"}


def get_video_metadata(file_path: str):
    """Use ffprobe to get width, height, and duration.

    Width/height are normalized for sample aspect ratio (non-square pixels),
    which is common in re-encoded/archival footage (e.g. old game captures).
    ffprobe's raw width/height are *coded* pixel dimensions; Telegram uses
    whatever width/height we attach to size the message's video container,
    but the client's own player renders the frame using its embedded SAR/DAR.
    If those disagree, the inline thumbnail (built from our metadata) can
    look fine while the full-screen player - which honors the real embedded
    aspect - shows letterboxing/distortion. Reporting square-pixel-equivalent
    dimensions keeps both in agreement.
    """
    try:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-select_streams", "v:0", "-show_entries",
            "stream=width,height,duration,sample_aspect_ratio", file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        import json
        data = json.loads(result.stdout)

        stream = data.get("streams", [{}])[0]
        width = stream.get("width", 720)
        height = stream.get("height", 1280)
        duration = int(float(stream.get("duration", 0))) if stream.get("duration") else 0

        sar = stream.get("sample_aspect_ratio")
        if sar and ":" in sar:
            try:
                sar_num, sar_den = (int(p) for p in sar.split(":", 1))
                if sar_num > 0 and sar_den > 0 and sar_num != sar_den:
                    width = round(width * sar_num / sar_den)
            except ValueError:
                pass

        return width, height, duration
    except Exception as e:
        logger.warning(f"Failed to get metadata for {file_path}: {e}")
        return 720, 1280, 0  # safe defaults for vertical video

# Quality tiers for private-chat downloads. `None` is the legacy default used
# for group chats (unchanged from the original hardcoded values). Tiers use
# CRF (quality-targeted) encoding except "xs", which pins an explicit bitrate
# since it needs to guarantee a small file size regardless of content.
TIER_PARAMS = {
    None: {"height": 720, "crf": "32", "audio_bitrate": "96k"},
    "high": {"height": 720, "crf": "28", "audio_bitrate": "128k"},
    "medium": {"height": 480, "crf": "30", "audio_bitrate": "96k"},
    "low": {"height": 360, "crf": "33", "audio_bitrate": "64k"},
    "xs": {"height": 360, "crf": "28", "audio_bitrate": "32k", "sample_rate": "11025"},
}


def generate_thumbnail(file_path: str, duration: int = 0) -> str | None:
    """Grab a JPEG frame to use as an explicit video thumbnail.

    Needed for the large-file (Telethon) upload path: Telethon doesn't
    auto-generate a thumbnail the way the direct bot API upload does, so
    without one Telegram clients show a black placeholder until the video is
    fully buffered. Seeking a bit into the video (rather than frame 0) avoids
    grabbing a fade-in/loading-screen black frame.
    """
    seek = min(duration, 5) if duration else 1
    output_path = os.path.splitext(file_path)[0] + "_thumb.jpg"
    cmd = [
        "ffmpeg", "-ss", str(seek), "-i", file_path,
        "-frames:v", "1", "-vf", "scale=320:-1",
        "-y", output_path,
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
        return output_path
    except Exception as e:
        logger.warning(f"Failed to generate thumbnail for {file_path}: {e}")
        return None


def _remux_faststart(input_path: str) -> str:
    """Stream-copy remux to move the moov atom to the front of the file, so
    Telegram's progressive player can render video instead of playing audio
    over a black screen. Cheap (no re-encode) so safe to use as a fallback
    whenever a real compression attempt fails or times out."""
    output_path = os.path.splitext(input_path)[0] + "_faststart.mp4"
    cmd = ["ffmpeg", "-i", input_path, "-c", "copy", "-movflags", "+faststart", "-y", output_path]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=5400)
        logger.info(f"✅ faststart remux fallback succeeded: {output_path}")
        if os.path.exists(input_path) and input_path != output_path:
            os.unlink(input_path)
        return output_path
    except Exception as e:
        logger.warning(f"faststart remux fallback failed for {input_path}: {e}")
        return input_path


def _run_ffmpeg(cmd: list[str], input_path: str, output_path: str, label: str, fallback_remux: bool = True) -> str:
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=3600)
        logger.info(f"✅ {label} succeeded: {output_path}")
        if os.path.exists(input_path) and input_path != output_path:
            os.unlink(input_path)
        return output_path
    except subprocess.TimeoutExpired:
        logger.warning(f"ffmpeg timeout - skipping {label} for {input_path}")
    except subprocess.CalledProcessError as e:
        stderr_text = (e.stderr or b"").decode(errors="replace").strip()[-2000:]
        logger.error(f"ffmpeg {label} failed (exit {e.returncode}) for {input_path}: {stderr_text or '(no stderr captured)'}")
    except Exception as e:
        logger.error(f"ffmpeg {label} failed: {e}")

    return _remux_faststart(input_path) if fallback_remux else input_path


def compress_video(input_path: str, tier: str | None = None) -> str:
    if not input_path.lower().endswith((".mp4", ".mov")):
        return input_path

    output_path = os.path.splitext(input_path)[0] + "_ios.mp4"

    if tier == "max":
        codec = _video_codec(input_path)
        if codec in TELEGRAM_COMPATIBLE_VIDEO_CODECS:
            # No re-encode (no quality/bitrate loss), but yt-dlp's raw merged
            # mp4 has its moov atom at the end of the file, so Telegram's
            # progressive player can play audio while showing a black frame
            # until the whole file downloads. Remux (stream copy) to move it
            # to the front.
            cmd = ["ffmpeg", "-i", input_path, "-c", "copy", "-movflags", "+faststart", "-y", output_path]
            return _run_ffmpeg(cmd, input_path, output_path, "faststart remux", fallback_remux=False)

        # The download step prefers H.264, but falls back to whatever's
        # available (e.g. an AV1-only source at very high resolutions).
        # Stream-copying an incompatible codec would still be unplayable, so
        # re-encode at a visually-lossless quality instead of true no-op copy.
        logger.info(f"max tier: source codec '{codec}' isn't broadly compatible, re-encoding near-lossless instead of copying")
        cmd = [
            "ffmpeg", "-i", input_path,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-threads", "2",
            "-y",
            output_path
        ]
        return _run_ffmpeg(cmd, input_path, output_path, "near-lossless re-encode")

    params = TIER_PARAMS.get(tier, TIER_PARAMS[None])
    vf = f"scale=-2:'min({params['height']},ih)'"

    cmd = ["ffmpeg", "-i", input_path, "-c:v", "libx264", "-preset", "veryfast"]
    if "video_bitrate" in params:
        cmd += [
            "-b:v", params["video_bitrate"],
            "-maxrate", params["video_bitrate"],
            "-bufsize", "300k",
        ]
    else:
        cmd += ["-crf", params["crf"]]     # Higher CRF = smaller size

    if "sample_rate" in params:
        cmd += [ "-ar", params["sample_rate"]]

    cmd += [
        "-c:a", "aac",
        "-b:a", params["audio_bitrate"],
        "-pix_fmt", "yuv420p",
        "-vf", vf,
        "-movflags", "+faststart",
        "-threads", "2",
        "-y",
        output_path
    ]

    return _run_ffmpeg(cmd, input_path, output_path, "iOS re-encode")

