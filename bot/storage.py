"""
Google Drive storage module for persistent data storage.

This module uses Google Drive API when configured, and falls back to a local JSON file
store when the cloud API is unavailable.
"""

import json
import os
import threading
from pathlib import Path
from typing import Any, Optional

import requests

from .config import logger

# Google Drive configuration
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")

LOCAL_STORAGE_ROOT = Path(
    os.getenv("BOT_STORAGE_DIR")
    or ("/data" if Path("/data").exists() else Path(__file__).resolve().parent.parent / "data")
)

# Try to import Google Drive dependencies
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_DRIVE_AVAILABLE = True
except ImportError:
    GOOGLE_DRIVE_AVAILABLE = False
    logger.warning("Google Drive dependencies not installed. Falling back to local storage.")


def _get_drive_service() -> Optional[Any]:
    """Create and return a Google Drive API service client."""
    if not GOOGLE_DRIVE_AVAILABLE:
        return None
    
    if not GOOGLE_DRIVE_FOLDER_ID or not GOOGLE_SERVICE_ACCOUNT_FILE:
        return None
    
    # Resolve the service account file path (relative to project root)
    project_root = Path(__file__).resolve().parent.parent
    service_account_path = project_root / GOOGLE_SERVICE_ACCOUNT_FILE
    
    if not service_account_path.exists():
        logger.warning(f"Service account file not found: {service_account_path}")
        return None
    
    try:
        credentials = service_account.Credentials.from_service_account_file(
            str(service_account_path),
            scopes=['https://www.googleapis.com/auth/drive']
        )
        service = build('drive', 'v3', credentials=credentials)
        return service
    except Exception as exc:
        logger.error(f"Failed to create Google Drive service: {exc}")
        return None


class GoogleDriveStorage:
    """Storage backend using Google Drive API with local file fallback."""
    
    def __init__(self, file_name: str, default_value: Any):
        self.file_name = file_name
        self.default_value = default_value
        self._lock = threading.Lock()
        self._local_cache: Any = None
        self._cache_loaded = False
        self._drive_service: Optional[Any] = None
        self._file_id: Optional[str] = None
        self._initialized = False
    
    def _local_path(self) -> Path:
        return LOCAL_STORAGE_ROOT / f"{self.file_name}.json"
    
    def _read_local(self) -> Any:
        path = self._local_path()
        if not path.exists():
            return self.default_value
        
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"Local storage read failed for '{self.file_name}': {exc}")
            return self.default_value
        
        return data
    
    def _write_local(self, data: Any) -> bool:
        try:
            self._local_path().parent.mkdir(parents=True, exist_ok=True)
            with self._local_path().open("w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=True, indent=2)
            return True
        except OSError as exc:
            logger.warning(f"Local storage write failed for '{self.file_name}': {exc}")
            return False
    
    def _ensure_initialized(self) -> bool:
        """Ensure the Drive service is available and file exists."""
        if self._initialized:
            return self._file_id is not None
        
        with self._lock:
            if self._initialized:
                return self._file_id is not None
            
            self._drive_service = _get_drive_service()
            if not self._drive_service or not GOOGLE_DRIVE_FOLDER_ID:
                self._initialized = True
                return False
            
            try:
                # Search for existing file in the folder
                query = f"name='{self.file_name}.json' and '{GOOGLE_DRIVE_FOLDER_ID}' in parents and trashed=false"
                response = self._drive_service.files().list(
                    q=query,
                    spaces='drive',
                    fields='files(id, name)'
                ).execute()
                
                files = response.get('files', [])
                if files:
                    self._file_id = files[0]['id']
                    logger.info(f"✅ Found Google Drive file '{self.file_name}.json' with ID: {self._file_id}")
                else:
                    # Create new file
                    from googleapiclient.http import MediaIoBaseUpload
                    
                    file_metadata = {
                        'name': f'{self.file_name}.json',
                        'parents': [GOOGLE_DRIVE_FOLDER_ID]
                    }
                    
                    # Prepare initial content
                    if self.default_value == []:
                        content = []
                    elif self.default_value is None or self.default_value == {}:
                        content = {}
                    else:
                        content = self.default_value
                    
                    import io
                    content_bytes = json.dumps(content, ensure_ascii=True).encode('utf-8')
                    media_body = io.BytesIO(content_bytes)
                    upload = MediaIoBaseUpload(media_body, mimetype='application/json')
                    
                    file = self._drive_service.files().create(
                        body=file_metadata,
                        media_body=upload,
                        fields='id'
                    ).execute()
                    
                    self._file_id = file.get('id')
                    logger.info(f"✅ Created Google Drive file '{self.file_name}.json' with ID: {self._file_id}")
                
                self._initialized = True
                return True
                
            except Exception as exc:
                logger.error(f"Failed to initialize Google Drive storage for '{self.file_name}': {exc}")
                self._initialized = True
                return False
    
    def read(self) -> Any:
        """Read data from Google Drive with local fallback."""
        if not self._ensure_initialized():
            return self._read_local()
        
        try:
            # Download file content
            request = self._drive_service.files().get_media(fileId=self._file_id)
            content = request.execute()
            
            if isinstance(content, bytes):
                content = content.decode('utf-8')
            
            data = json.loads(content)
            return data
            
        except HttpError as exc:
            if exc.resp.status == 404:
                logger.warning(f"Google Drive file '{self.file_name}' not found, recreating")
                with self._lock:
                    self._file_id = None
                    self._initialized = False
                if self._ensure_initialized():
                    return self.default_value
            else:
                logger.warning(f"Google Drive read failed for '{self.file_name}': {exc}")
        except Exception as exc:
            logger.warning(f"Google Drive read error for '{self.file_name}': {exc}")
        
        return self._read_local()
    
    def write(self, data: Any) -> bool:
        """Write data to Google Drive with local fallback."""
        if not self._ensure_initialized():
            return self._write_local(data)
        
        try:
            import io
            from googleapiclient.http import MediaIoBaseUpload
            
            content_bytes = json.dumps(data, ensure_ascii=True).encode('utf-8')
            media_body = io.BytesIO(content_bytes)
            upload = MediaIoBaseUpload(media_body, mimetype='application/json')
            
            # Update file content
            self._drive_service.files().update(
                fileId=self._file_id,
                media_body=upload
            ).execute()
            
            return True
            
        except HttpError as exc:
            if exc.resp.status == 404:
                logger.warning(f"Google Drive file '{self.file_name}' not found during write, recreating")
                with self._lock:
                    self._file_id = None
                    self._initialized = False
                if self._ensure_initialized():
                    return self.write(data)
            else:
                logger.warning(f"Google Drive write failed for '{self.file_name}': {exc}")
        except Exception as exc:
            logger.warning(f"Google Drive write error for '{self.file_name}': {exc}")
        
        return self._write_local(data)
    
    def clear_cache(self) -> None:
        self._cache_loaded = False
        self._local_cache = None


# Storage instances
_activated_chats_storage = None
_doorman_chats_storage = None
_moderators_storage = None
_access_requests_storage = None


def _get_activated_chats_storage() -> GoogleDriveStorage:
    global _activated_chats_storage
    if _activated_chats_storage is None:
        _activated_chats_storage = GoogleDriveStorage(
            file_name="activated_chats",
            default_value=[],
        )
    return _activated_chats_storage


def _get_doorman_chats_storage() -> GoogleDriveStorage:
    global _doorman_chats_storage
    if _doorman_chats_storage is None:
        _doorman_chats_storage = GoogleDriveStorage(
            file_name="doorman_chats",
            default_value=[],
        )
    return _doorman_chats_storage


def _get_moderators_storage() -> GoogleDriveStorage:
    global _moderators_storage
    if _moderators_storage is None:
        _moderators_storage = GoogleDriveStorage(
            file_name="moderators",
            default_value={"moderators": {}},
        )
    return _moderators_storage


def _get_access_requests_storage() -> GoogleDriveStorage:
    global _access_requests_storage
    if _access_requests_storage is None:
        _access_requests_storage = GoogleDriveStorage(
            file_name="access_requests",
            default_value=[],
        )
    return _access_requests_storage


def load_activated_chats() -> set[int]:
    data = _get_activated_chats_storage().read()
    return set(data) if isinstance(data, list) else set()


def save_activated_chats(chats: set[int]) -> None:
    storage = _get_activated_chats_storage()
    data = list(chats)
    success = storage.write(data)
    logger.debug("Saved activated chats: %s (success: %s)", data, success)


def load_doorman_chats() -> set[int]:
    data = _get_doorman_chats_storage().read()
    return set(data) if isinstance(data, list) else set()


def save_doorman_chats(chats: set[int]) -> None:
    storage = _get_doorman_chats_storage()
    data = list(chats)
    success = storage.write(data)
    logger.debug("Saved doorman chats: %s (success: %s)", data, success)


def load_moderators_from_storage() -> dict[int, list[int]]:
    """Load moderators from Google Drive storage.
    
    The data is stored with a 'moderators' wrapper key to avoid issues with empty objects.
    """
    data = _get_moderators_storage().read()
    # Handle the wrapper object {"moderators": {...}}
    if isinstance(data, dict):
        # If data has a "moderators" key, extract it
        if "moderators" in data:
            moderators_data = data["moderators"]
            if isinstance(moderators_data, dict):
                return {int(k): v for k, v in moderators_data.items()}
        # Otherwise, if data is already the moderators dict (non-empty), use it directly
        elif data:
            return {int(k): v for k, v in data.items()}
    return {}


def save_moderators_to_storage(moderators_data: dict[int, set[int]]) -> None:
    """Save moderators to Google Drive storage.
    
    The data is stored with a 'moderators' wrapper key to avoid issues with empty objects.
    """
    storage = _get_moderators_storage()
    # Wrap the data in a "moderators" key
    data = {"moderators": {str(k): list(v) for k, v in moderators_data.items()}}
    success = storage.write(data)
    logger.debug("Saved moderators: %s (success: %s)", data, success)


def load_access_requests_from_storage() -> list[dict]:
    """Load access requests from Google Drive storage."""
    data = _get_access_requests_storage().read()
    if isinstance(data, list):
        return data
    return []


def save_access_requests_to_storage(requests_data: list[dict]) -> None:
    """Save access requests to Google Drive storage."""
    storage = _get_access_requests_storage()
    success = storage.write(requests_data)
    logger.debug("Saved access requests: %s (success: %s)", requests_data, success)


def clear_all_caches() -> None:
    if _activated_chats_storage:
        _activated_chats_storage.clear_cache()
    if _doorman_chats_storage:
        _doorman_chats_storage.clear_cache()
    if _access_requests_storage:
        _access_requests_storage.clear_cache()


def get_storage_info() -> dict:
    return {
        "storage_type": "google_drive" if GOOGLE_DRIVE_FOLDER_ID else "local",
        "folder_id": GOOGLE_DRIVE_FOLDER_ID,
        "files": {
            "activated_chats": _get_activated_chats_storage()._file_id,
            "doorman_chats": _get_doorman_chats_storage()._file_id,
            "moderators": _get_moderators_storage()._file_id,
            "access_requests": _get_access_requests_storage()._file_id,
        },
    }


# ============================================================================
# Cookie Storage Functions (Google Drive, read-only, no fallback)
# ============================================================================

def _load_cookie_from_drive(file_name: str) -> str:
    """Load cookie content from Google Drive (no local fallback).
    
    Args:
        file_name: The name of the cookie file (e.g., 'instagram_cookies.txt')
    
    Returns:
        The cookie content as a string, or empty string if not found.
    """
    service = _get_drive_service()
    if not service or not GOOGLE_DRIVE_FOLDER_ID:
        logger.warning(f"Google Drive not configured for {file_name}")
        return ""
    
    try:
        # Search for the cookie file in the Drive folder
        query = f"name='{file_name}' and '{GOOGLE_DRIVE_FOLDER_ID}' in parents and trashed=false"
        response = service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)'
        ).execute()
        
        files = response.get('files', [])
        if not files:
            logger.debug(f"Cookie file '{file_name}' not found in Google Drive")
            return ""
        
        # Download file content
        file_id = files[0]['id']
        request = service.files().get_media(fileId=file_id)
        content = request.execute()
        
        if isinstance(content, bytes):
            content = content.decode('utf-8')
        
        logger.info(f"✅ Loaded '{file_name}' from Google Drive")
        return content
        
    except Exception as exc:
        logger.error(f"Failed to load '{file_name}' from Google Drive: {exc}")
        return ""


def load_instagram_cookies() -> str:
    """Load Instagram cookies from Google Drive storage (no fallback).
    
    Returns:
        The cookies content as a string, or empty string if not found.
    """
    return _load_cookie_from_drive("instagram_cookies.txt")


def load_facebook_cookies() -> str:
    """Load Facebook cookies from Google Drive storage (no fallback).
    
    Returns:
        The cookies content as a string, or empty string if not found.
    """
    return _load_cookie_from_drive("facebook_cookies.txt")

def load_youtube_cookies() -> str:
    """Load YouTube cookies from Google Drive storage (no fallback).
    
    Returns:
        The cookies content as a string, or empty string if not found.
    """
    return _load_cookie_from_drive("youtube_cookies.txt")


# ============================================================================
# Large File Upload to Google Drive (Legacy - kept for backward compatibility)
# ============================================================================

# Default folder ID for large file uploads (from user configuration)
# https://drive.google.com/drive/folders/1ldBfxj2GQ8hsUzR17423Gr1E5R0-m1Fk?usp=sharing
LARGE_FILE_FOLDER_ID = os.getenv("LARGE_FILE_FOLDER_ID", "1ldBfxj2GQ8hsUzR17423Gr1E5R0-m1Fk")


def upload_file_to_drive(file_path: str, folder_id: str = LARGE_FILE_FOLDER_ID) -> str:
    """
    Upload a file to Google Drive and return a shareable link.
    
    IMPORTANT: Service accounts require a Shared Drive (not regular My Drive) to upload files.
    See: https://developers.google.com/workspace/drive/api/guides/manage-shareddrives
    
    Args:
        file_path: Path to the file to upload
        folder_id: Google Drive folder ID (must be in a Shared Drive for service accounts)
    
    Returns:
        Shareable link to the uploaded file, or empty string if upload fails
    """
    service = _get_drive_service()
    if not service:
        logger.error("Google Drive service not available for file upload")
        return ""
    
    if not folder_id:
        logger.error("No folder ID provided for file upload")
        return ""
    
    try:
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        
        logger.info(f"Uploading file to Google Drive: {file_name} ({file_size / (1024*1024):.1f}MB)")
        
        # Create file metadata
        file_metadata = {
            'name': file_name,
            'parents': [folder_id]
        }
        
        # Upload file with Shared Drive support
        from googleapiclient.http import MediaFileUpload
        media = MediaFileUpload(
            file_path,
            mimetype='application/octet-stream',
            resumable=True,
            chunksize=256 * 1024  # 256KB chunks
        )
        
        request = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name, webContentLink, webViewLink',
            supportsAllDrives=True  # Important for Shared Drives
        )
        
        uploaded_file = request.execute()
        file_id = uploaded_file.get('id')
        
        if not file_id:
            logger.error(f"File upload failed: no file ID returned")
            return ""
        
        logger.info(f"✅ File uploaded to Google Drive: {uploaded_file.get('name')} (ID: {file_id})")
        
        # Set permissions: anyone with link can view/download
        # For Shared Drives, we need to set inheritFromParent=False
        permission = {
            'type': 'anyone',
            'role': 'reader'
        }
        
        service.permissions().create(
            fileId=file_id,
            body=permission,
            fields='id',
            supportsAllDrives=True  # Important for Shared Drives
        ).execute()
        
        # Get the shareable link
        file_info = service.files().get(
            fileId=file_id,
            fields='webContentLink, webViewLink',
            supportsAllDrives=True  # Important for Shared Drives
        ).execute()
        
        # Prefer webContentLink (direct download link) over webViewLink
        shareable_link = file_info.get('webContentLink') or file_info.get('webViewLink')
        
        if shareable_link:
            logger.info(f"✅ Shareable link created: {shareable_link}")
            return shareable_link
        else:
            logger.warning(f"File uploaded but no shareable link available")
            return f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
        
    except Exception as exc:
        # Check for storage quota error (common with service accounts on regular Drive)
        if hasattr(exc, 'resp') and getattr(exc.resp, 'status', None) == 403:
            error_details = str(exc)
            if 'storageQuotaExceeded' in error_details or 'Service Accounts do not have storage quota' in error_details:
                logger.error(
                    "❌ Storage quota exceeded. Service accounts cannot upload to regular My Drive folders.\n"
                    "SOLUTION: Use a Shared Drive instead.\n"
                    "1. Create a Shared Drive: https://drive.google.com/drive/create\n"
                    "2. Add your service account email as 'Content Manager'\n"
                    "3. Create a folder in the Shared Drive\n"
                    "4. Set LARGE_FILE_FOLDER_ID env var to that folder's ID\n\n"
                    "See: https://developers.google.com/workspace/drive/api/guides/manage-shareddrives"
                )
        logger.error(f"Failed to upload file to Google Drive: {exc}")
        return ""
