# GPU-accelerated video compression with CPU fallback (future work)

## Status

Not yet implemented. The immediate stop-gap (bumping ffmpeg timeouts in `bot/video.py` from 90s/60s to 3600s/5400s) has already been applied separately. This document is the plan for the actual GPU-encoding follow-up.

## Context

`bot/video.py`'s `compress_video()` currently always re-encodes with CPU-only `libx264` (`-preset veryfast`). On long videos this can hit the ffmpeg timeout, which previously caused a black-video bug and now falls back to a faststart-only remux (no compression) — a correctness fallback, but it'd be better to avoid needing it by encoding faster in the first place.

The bot runs in two environments with different, unconfirmed GPU situations:
- **Windows dev machine**: confirmed NVIDIA GPU.
- **Proxmox Debian LXC** (release/production target): no dedicated GPU; likely an Intel integrated GPU, but GPU passthrough into the LXC hasn't been checked/confirmed yet.

Since the two environments differ and the production GPU passthrough status is unknown/likely-not-yet-set-up, the right design is **runtime auto-detection with a safe, silent CPU fallback** — not hardcoding a vendor. This way the same code:
- Uses NVENC on the Windows dev box today.
- Automatically starts using Intel Quick Sync (QSV) on the Proxmox LXC once/if `/dev/dri` passthrough and the needed VAAPI/QSV runtime packages are wired up there — with zero further code changes.
- Behaves exactly as it does today (CPU libx264) anywhere hardware encoding isn't available, so this is a no-op risk-wise until GPU passthrough is actually confirmed working.

## Implementation — `bot/video.py`

1. **One-time hardware encoder probe** — new function `_detect_hw_encoder() -> str | None`, cached at module level (e.g. via a `_HW_ENCODER` sentinel variable set on first call) so the probe only runs once per process, not once per video:
   - Try candidates in priority order: `h264_nvenc`, `h264_qsv`, `h264_amf`.
   - For each, run a cheap real verification encode (presence in `ffmpeg -encoders` doesn't guarantee the driver/device actually works at runtime — e.g. NVENC support can be compiled in but fail with "Cannot init CUDA" if there's no GPU/driver):
     ```
     ffmpeg -f lavfi -i nullsrc=s=64x64:d=1:r=1 -c:v <candidate> -frames:v 1 -f null -
     ```
     short timeout (~5s), suppressed output, `check=True`.
   - First candidate that succeeds wins; log which encoder was selected. If none succeed, cache `None` and log that CPU (`libx264`) will be used.

2. **Per-encoder rate-control mapping** — small helper (e.g. `_encoder_args(encoder, params) -> list[str]`) that translates the existing `TIER_PARAMS` values (`crf` or `video_bitrate` + `audio_bitrate`) into each backend's equivalent flags, so `TIER_PARAMS` itself stays the single source of truth for tier definitions:
   - `libx264` (current/unchanged): `-preset veryfast -crf <crf>` or `-b:v/-maxrate/-bufsize` for bitrate tiers (xs).
   - `h264_nvenc`: `-preset p4 -rc vbr -cq <crf> -b:v 0` for CRF tiers; `-rc cbr -b:v <rate> -maxrate <rate> -bufsize 300k` for bitrate tiers (xs).
   - `h264_qsv`: `-preset veryfast -global_quality <crf>` for CRF tiers; same bitrate-tier flags as above (`-b:v`/`-maxrate`/`-bufsize` is common across encoders).
   - `h264_amf`: `-quality speed -rc cqp -qp_i <crf> -qp_p <crf>` for CRF tiers; `-rc cbr -b:v <rate> -maxrate <rate>` for bitrate tiers.
   - Shared across all backends, unchanged: `-c:a aac -b:a <rate> -pix_fmt yuv420p -vf scale=-2:'min(H,ih)' -movflags +faststart -y <output>`. (`-threads 2` stays libx264-only; irrelevant for hardware encoders.)
   - CRF values are reused as an approximation of each vendor's quality knob — not a byte-for-byte size guarantee, since encoders don't share a quality curve. That's an acceptable trade for "encode fast, else fall back to the known-good CPU path."

3. **`compress_video()` control flow** (non-`"max"` tiers only — `"max"` stays stream-copy, untouched, no encoder involved):
   - Look up `encoder = _detect_hw_encoder()`.
   - If an encoder was found: build the hardware cmd, run via `_run_ffmpeg(cmd, input_path, output_path, f"{encoder} re-encode", fallback_remux=False)`.
     - Success is detectable the same way `_run_ffmpeg` already signals it: returned path `!= input_path`.
     - On failure (a probe can pass but a specific real file can still fail/timeout mid-run — e.g. transient driver hiccup), log a warning and fall through to CPU rather than giving up.
   - Build the existing `libx264` cmd and run via `_run_ffmpeg(..., fallback_remux=True)` (default) — this is exactly today's code path/behavior, so the CPU route and its existing faststart-remux safety net for real failures are both unchanged.
   - Net effect: GPU attempted first when available and working, CPU libx264 as the fallback, faststart remux as the final safety net — same guarantees as today, just faster when hardware encoding is usable.

4. No changes to `TIER_PARAMS`, `handlers.py`, `worker.py`, or the `"max"`-tier remux path — this is scoped entirely to how the non-`max` re-encode step picks its encoder.

## Verification

- **Windows dev machine**: run the bot locally, send a video through the private-chat quality picker (e.g. "medium" tier), confirm the log line shows `h264_nvenc` was detected/used, confirm the resulting video plays correctly (not black) and compresses noticeably faster than before.
- **Regression check for CPU fallback**: temporarily force `_detect_hw_encoder()` to return `None` (or test on a non-GPU machine) and confirm output is identical in behavior to the current `libx264` path — same flags, same fallback-to-remux behavior on failure/timeout.
- **Proxmox LXC**: after deploying, check the logs for which encoder (if any) was detected. If Intel passthrough isn't configured yet, it should log "no hardware encoder found, using libx264" and behave exactly as production does today — confirming the change is a safe no-op there until `/dev/dri` passthrough + QSV/VAAPI runtime packages are separately set up in that container (outside this code change's scope).
