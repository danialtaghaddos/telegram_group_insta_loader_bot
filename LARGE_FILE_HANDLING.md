# Large Audio File Handling (>50MB)

## Overview

When a YouTube audio file exceeds Telegram's 50MB upload limit, the bot now gives users a choice between two options:

1. **🗜️ Compress & Send** - Compress the audio file and send via Telegram
2. **📁 Google Drive** - Upload to Google Drive and send a download link

## Implementation Details

### Files Modified

1. **`bot/utils.py`** - Added `compress_audio()` function
2. **`bot/storage.py`** - Added `upload_file_to_drive()` function
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
Compress    Google Drive
   │             │
   ↓             ↓
Check size   Upload to Drive
   │          Send link
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

If compression doesn't reduce the file below 50MB, the bot automatically falls back to Google Drive upload.

### Google Drive Configuration

- **Folder ID**: `1ldBfxj2GQ8hsUzR17423Gr1E5R0-m1Fk` (default, configurable via `LARGE_FILE_FOLDER_ID` env var)
- **Permissions**: Anyone with link can view/download
- **Service Account**: Uses existing Google Drive service account configuration

### ⚠️ IMPORTANT: Shared Drive Requirement

**Service accounts cannot upload files to regular "My Drive" folders** because they have no storage quota. You must use a **Shared Drive** instead.

#### Setup Instructions

1. **Create a Shared Drive**:
   - Go to <https://drive.google.com/drive/create>
   - Give it a name (e.g., "Bot Uploads")

2. **Add Service Account as Member**:
   - Open the Shared Drive settings
   - Click "Manage members"
   - Add your service account email (found in your `gc-service-account.json` file, look for `client_email`)
   - Assign role: **Content Manager**

3. **Create a Folder in the Shared Drive**:
   - Open the Shared Drive
   - Create a new folder (e.g., "temp_upload")
   - Copy the folder ID from the URL

4. **Update Environment Variable**:

   ```bash
   LARGE_FILE_FOLDER_ID=your_new_folder_id_here
   ```

#### How to Find Your Service Account Email

Open your `gc-service-account.json` file and look for:

```json
{
  "type": "service_account",
  "project_id": "...",
  "private_key_id": "...",
  "client_email": "your-bot@project.iam.gserviceaccount.com",  ← This is the email
  ...
}
```

#### How to Get Folder ID from URL

When you open a folder in Google Drive, the URL looks like:

```
https://drive.google.com/drive/folders/1ABCdefGHIjklMNOpqrSTUvwxYZ123456
```

The folder ID is: `1ABCdefGHIjklMNOpqrSTUvwxYZ123456`

### Environment Variables

```bash
# Optional: Override the default Google Drive folder for large files
LARGE_FILE_FOLDER_ID=your_folder_id_here
```

### Error Handling

- If compression fails → Fall back to Google Drive
- If Google Drive upload fails → Show error message
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
   - **Drive**: Shows "📁 Uploading to Google Drive..." then sends link

3. Google Drive message format:

   ```
   📁 File uploaded to Google Drive (75.3MB):

   https://drive.google.com/...

   Click the link to download.
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
- [ ] File > 50MB, user chooses Drive → Uploads to Drive and sends link
- [ ] Compression fails → Falls back to Drive
- [ ] Drive upload fails → Shows error message
- [ ] User cancels during wait → Stops processing
