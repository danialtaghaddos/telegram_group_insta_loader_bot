# Local Bot API server + deployment cleanup (plan, not yet implemented)

## Context

This started as a question about whether uploading large files to a private channel instead of the admin's DM would speed things up (it wouldn't — upload speed is bandwidth-bound, not destination-bound). That led to a better answer: Telegram's official **local Bot API server** (`tdlib/telegram-bot-api`) raises the direct-upload ceiling from 50MB to ~2GB, which would let the bot send big files itself instead of relaying them through the admin's Telethon account. The user wants this implemented.

While discussing it, the user also clarified the real deployment target: a **Proxmox LXC Debian container**, run via the existing `install_on_debian.sh` script — not Docker, not Termux/Android. Those other two deployment paths are legacy and the user wants them removed:
- GitHub Actions Docker CI (`.github/workflows/docker-build.yml`) and `Dockerfile`
- Termux/Android docs and scripts (`termux_setup.md`, `install_on_termux.sh`, `QUICK_START_ANDROID.md`, `.termux/`)

Both changes are independent but landing together.

## Part 1 — Local Bot API server (raises 50MB → ~2GB direct uploads)

### Feasibility finding (already researched)

PTB 21.0's `InputFile`/`load_file` does an **eager, unbounded `.read()`** of the whole file into `bytes` *before* any network I/O — confirmed by reading `telegram/_files/inputfile.py` and `telegram/request/_httpxrequest.py` in the installed package. That means a naive "wrap the file object and count `.read()` calls" progress tracker would report 0%→100% instantly, with no relation to real upload progress. So: **bypass PTB for the large-file path** and stream the multipart POST to the local server ourselves via `httpx`, which *does* read a genuine file-like object lazily as it writes to the socket — giving real progress. Parse the JSON response back into a `telegram.Message` via `Message.de_json(...)` so the rest of the code (`sent.chat_id`, `sent.message_id`) keeps working unchanged.

### 1a. Installing `telegram-bot-api` on the Debian LXC (new script)

New `install_telegram_bot_api.sh` (sibling to the existing `install_on_debian.sh`, same root-required/Debian-check style):

```bash
apt-get update -y
apt-get install -y build-essential cmake git zlib1g-dev libssl-dev gperf
cd /opt
git clone --recursive https://github.com/tdlib/telegram-bot-api.git
cd telegram-bot-api && mkdir -p build && cd build
cmake -DCMAKE_BUILD_TYPE=Release ..
cmake --build . --target install -j"$(nproc)"
mkdir -p /var/lib/telegram-bot-api
```

Installs the binary to `/usr/local/bin/telegram-bot-api` (cmake default). Then write and enable a systemd unit `/etc/systemd/system/telegram-bot-api.service`:

```ini
[Unit]
Description=Telegram Bot API local server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
EnvironmentFile=<BOT_DIR>/.env
WorkingDirectory=/var/lib/telegram-bot-api
ExecStart=/usr/local/bin/telegram-bot-api --local --api-id=${TELEGRAM_API_ID} --api-hash=${TELEGRAM_API_HASH} --http-port=8081 --dir=/var/lib/telegram-bot-api
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Reuses the **existing** `TELEGRAM_API_ID`/`TELEGRAM_API_HASH` from `.env` (already there for Telethon) — no new Telegram credentials needed. If `${VAR}` expansion inside `ExecStart=` proves unreliable on the target systemd version, fall back to a tiny wrapper shell script that does `exec telegram-bot-api --api-id="$TELEGRAM_API_ID" ...`. End the script with `systemctl daemon-reload && systemctl enable --now telegram-bot-api`, matching `install_on_debian.sh`'s existing pattern.

Add `After=telegram-bot-api.service` to the bot's own unit (inside `install_on_debian.sh`'s heredoc) so it starts after the local server when both are present — but **not** `Requires=`, since the local server is optional and the bot must keep working without it (falls back to the public Bot API / Telethon relay).

Mention this new script as an optional step in `install_on_debian.sh`'s final "Next steps" output.

### 1b. Wiring the bot to use it

**`bot/config.py`** — add:
```python
LOCAL_BOT_API_URL = os.getenv("LOCAL_BOT_API_URL")  # e.g. "http://127.0.0.1:8081"; unset = public Bot API
LOCAL_BOT_API_ENABLED = bool(LOCAL_BOT_API_URL)
MAX_DIRECT_UPLOAD_MB = 1950  # headroom under telegram-bot-api's 2000MB local-mode ceiling
```

**`bot/main.py`** — in `main()`, before `.build()`, conditionally set `.base_url(f"{url}/bot")` / `.base_file_url(f"{url}/file/bot")` when `LOCAL_BOT_API_URL` is set. Fully opt-in/backward compatible — unset env var means identical behavior to today.

### 1c. New module `bot/local_bot_api.py`

- `_ProgressFileReader` — wraps an open file handle; `.read()` delegates to the underlying file and reports cumulative bytes via a callback (httpx calls this lazily during the real socket write, unlike PTB's path).
- `send_large_file_direct(...)` — builds the multipart POST by hand (`chat_id`, the file field, and whatever extra fields the specific method needs — e.g. `supports_streaming`/`width`/`height`/`duration`/`caption`/`reply_to_message_id` for video), posts to `{LOCAL_BOT_API_URL}/bot{BOT_TOKEN}/{method}` via `httpx.AsyncClient`, and returns `Message.de_json(response["result"], ...)`.

### 1d. `bot/worker.py` changes

- Compute `effective_ceiling = MAX_DIRECT_UPLOAD_MB if LOCAL_BOT_API_ENABLED else 50`, replacing both existing `file_size_mb > 50` checks (audio branch, video branch) with `> effective_ceiling`. **Preserve the existing asymmetry as-is**: the audio branch's oversized-file check today is not gated by `is_private` (Telethon relay can trigger in groups too), the video branch's is (`is_private and file_size_mb > 50`) — just swap the threshold, don't "fix" that inconsistency as a drive-by change.
- Extract each branch's existing Telethon-relay block (status edits, `upload_to_admin_chat` call, `large_file_captions` stash, cleanup/`continue`) into a small local helper so it can be reused both when a file exceeds `effective_ceiling` *and* as the except-path fallback below — avoids duplicating ~20 lines twice per branch.
- For files between 50MB and `effective_ceiling` (i.e. only reachable when `LOCAL_BOT_API_ENABLED`): call `send_large_file_direct(...)` instead of `reply_video`/`send_video`/`reply_audio`/`send_audio`, passing a progress callback built from the **existing** `_make_progress_callback(status_msg)` helper (same 5%/2s throttling already used by the Telethon path) when `is_private` (mirrors the existing group-vs-private progress-message gating), `None` otherwise. Wrap the call in `try/except` — on failure (`NetworkError`/`TimedOut`/`BadRequest`/connection refused), log a warning and fall through to the same Telethon-relay helper used above, so a down/misconfigured local server never breaks uploads, it just becomes slower (matches the "keep Telethon as rare fallback" decision).
- Files ≤ 50MB keep today's plain `reply_video`/`send_video`/etc. — unchanged, no added complexity for the common case.

### 1e. Docs

- `CLAUDE.md`: extend the "Download Flow" section (item 4, already describing the Telethon relay) to describe the local-server path as primary and Telethon as the fallback, referencing `bot/local_bot_api.py` and the `LOCAL_BOT_API_URL`/`MAX_DIRECT_UPLOAD_MB` config.
- `README.md`: add `LOCAL_BOT_API_URL` to the environment-variables table.

## Part 2 — Remove Docker and Termux deployment paths

Delete outright:
- `Dockerfile`
- `.github/workflows/docker-build.yml`
- `termux_setup.md`
- `install_on_termux.sh`
- `QUICK_START_ANDROID.md`
- `.termux/` (whole directory, including `boot/start-bot.sh`)

Edit `README.md`'s "Deployment Options" section:
- Remove the "Android Phone (Termux)" subsection (and its link to `QUICK_START_ANDROID.md`).
- Remove the "Docker" and "Docker Compose" subsections.
- Add a "Proxmox LXC / Debian" subsection pointing at the existing (already-in-repo, currently undocumented in README) `install_on_debian.sh`, and mention `install_telegram_bot_api.sh` from Part 1 as an optional follow-up step for >50MB uploads.
- Keep "Direct Python" as-is.

Edit `CLAUDE.md`'s project-structure listing: drop the `Dockerfile` line.

Edit `.cline_rules`'s project-structure listing: drop the `Dockerfile` line. (This file is already fairly stale/out of sync with `CLAUDE.md` in other ways — out of scope to fully rewrite here, just remove the Docker reference so it doesn't point at a deleted file.)

## Verification

- `python -m py_compile` on all touched/new `.py` files (`bot/config.py`, `bot/main.py`, `bot/worker.py`, `bot/local_bot_api.py`).
- Manually confirm `LOCAL_BOT_API_URL` unset ⇒ `ApplicationBuilder` uses default `api.telegram.org` base URLs (grep the built `Bot` object's `base_url`, or just confirm the conditional is skipped).
- No live end-to-end test of the local Bot API server itself is possible from here (needs the actual Proxmox LXC + a running `telegram-bot-api` process + real Telegram credentials) — flag to the user that they'll need to run `install_telegram_bot_api.sh` on the actual container and set `LOCAL_BOT_API_URL` in `.env` to smoke-test a real >50MB upload before relying on it.
- `git status` / `git grep -i docker` / `git grep -i termux` after deletions to confirm no dangling references remain outside what's intentionally left (e.g. none expected).
