# Large Audio File Handling (>50MB)

## Overview

When a YouTube audio file exceeds Telegram's 50MB upload limit, the bot gives users a choice between two options:

1. **🗜️ Compress & Send** - Compress the audio file and send via Telegram
2. **📁 Cloud Storage** - Upload to Google Cloud Storage and send a download link

## Implementation Details

### Files Modified

1. **`bot/utils.py`** - Added `compress_audio()` function
2. **`bot/storage.py`** - Added `upload_file_to_gcs()` function
3. **`bot/handlers.py`** - Added `handle_large_file_callback()` handler
4. **`bot/worker.py`** - Modified audio handling logic to check size and show choices
5. **`bot/main.py`** - Registered new callback handler

### Flow

```txt
User sends YouTube URL
        ↓
Download audio (yt-dlp)
        ↓
Check file size
        ↓
   ┌────┴────┐
   │ > 50MB? │
   └────┬────┘
        │
   Yes  │  No
   ┌────┴────┐
   │  Show   │  → Upload to Telegram normally
   │ choices │
   └────┬────┘
        │
   ┌────┴────────────────┐
   │ User selects option │
   └────┬────────────────┘
        │
   ┌────┴────────┐
   │             │
Compress    Cloud Storage
   │             │
   ↓             ↓
Check size   Upload to GCS
   │          Send signed URL
   │             │
   │        ┌────┴────┐
   │        │ Success?│
   │        └────┬────┘
   │             │
   ↓             ↓
Upload to   Send link
Telegram    or error
```

### Compression Details

- **Default bitrate**: 96kbps (configurable)
- **Codec**: AAC for M4A, MP3 for MP3, Opus for OPUS
- **Sample rate**: 44.1kHz
- **Channels**: Stereo (2)

If compression doesn't reduce the file below 50MB, the bot automatically falls back to Google Cloud Storage upload.

### Google Cloud Storage Configuration

- **Bucket**: `mehreran-telegram-bot-storage` (configurable via `GCS_BUCKET_NAME` env var)
- **Location**: asia-southeast1 (Singapore)
- **Signed URL validity**: 7 days
- **File organization**: Files are uploaded to `uploads/` folder in the bucket

### Environment Variables

```bash
# Google Cloud Storage bucket for large file uploads
GCS_BUCKET_NAME=mehreran-telegram-bot-storage
```

### Error Handling

- If compression fails → Fall back to Google Cloud Storage
- If GCS upload fails → Show error message
- If user cancels during wait → Clean up and stop
- If timeout waiting for user choice → Stop processing

### User Experience

1. When a large file is detected, the bot shows:

   ```
   ⚠️ Audio file is 75.3MB (limit is 50MB).

   Choose an option:
   [🗜️ Compress & Send]
   [📁 Google Drive]
   ```

2. After user selects:
   - **Compress**: Shows "🗜️ Compressing audio..." then uploads
   - **Cloud Storage**: Shows "📁 Uploading to cloud storage..." then sends link

3. Cloud Storage message format:

   ```
   📁 File uploaded to cloud storage (75.3MB):

   https://storage.googleapis.com/...

   Click the link to download. (Valid for 7 days)
   ```

## Testing

To test this feature:

1. Find a YouTube video that's longer than ~1 hour (or high bitrate)
2. Send the URL to the bot
3. Choose "Download Audio"
4. When the size warning appears, select an option
5. Verify the result

### Test Cases

- [ ] File < 50MB → Uploads directly to Telegram
- [ ] File > 50MB, user chooses Compress → Compresses and uploads
- [ ] File > 50MB, user chooses Cloud Storage → Uploads to GCS and sends link
- [ ] Compression fails → Falls back to Cloud Storage
- [ ] GCS upload fails → Shows error message
- [ ] User cancels during wait → Stops processing
