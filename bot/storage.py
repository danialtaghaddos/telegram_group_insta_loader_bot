"""
JSONBin.io storage module for persistent data storage.

This module provides a cloud-based storage solution using JSONBin.io API,
with automatic bin management. Only the API key is required - all bin IDs
are stored in a master metadata bin on JSONBin.io.
"""
import json
import os
import threading
from typing import Any, Optional

import requests

from .config import logger

# JSONBin.io API configuration
JSONBIN_API_BASE = "https://api.jsonbin.io/v3"
JSONBIN_API_KEY = os.getenv("JSONBIN_API_KEY")

# Local fallback paths (used when JSONBin.io is not configured or fails)
LOCAL_DATA_DIR = os.getenv("LOCAL_DATA_DIR", "/data")
LOCAL_ACTIVATED_CHATS = os.path.join(LOCAL_DATA_DIR, "activated_chats.json")
LOCAL_DOORMAN_CHATS = os.path.join(LOCAL_DATA_DIR, "doorman_chats.json")
LOCAL_ACTIVATION_REQUESTS = os.path.join(LOCAL_DATA_DIR, "activation_requests.json")

# Master metadata bin name (stores all bin IDs)
MASTER_BIN_NAME = "telegram_bot_storage_metadata"
MASTER_BIN_ENV = os.getenv("JSONBIN_MASTER_BIN_ID")


class MasterBinManager:
    """
    Manages the master metadata bin that stores all other bin IDs.
    This allows the system to work without storing bin IDs in environment variables.
    """
    
    def __init__(self):
        self.bin_id = MASTER_BIN_ENV
        self._cache = None
        self._lock = threading.Lock()
    
    def _get_headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "X-Master-Key": JSONBIN_API_KEY
        }
    
    def get_bin_ids(self) -> dict:
        """Get all bin IDs from the master metadata bin."""
        with self._lock:
            if self._cache is not None:
                return self._cache
            
            if not JSONBIN_API_KEY:
                return {}
            
            # Try to read existing master bin
            if self.bin_id:
                try:
                    url = f"{JSONBIN_API_BASE}/b/{self.bin_id}/latest"
                    headers = self._get_headers()
                    headers["X-Bin-Meta"] = "false"
                    response = requests.get(url, headers=headers, timeout=10)
                    
                    if response.status_code == 200:
                        self._cache = response.json()
                        return self._cache
                except Exception as e:
                    logger.warning(f"Error reading master bin: {e}")
            
            # If no bin_id or read failed, try to find by listing bins (not supported by JSONBin)
            # So we'll just return empty dict - bins will be created as needed
            self._cache = {}
            return self._cache
    
    def save_bin_id(self, bin_name: str, bin_id: str) -> bool:
        """Save a bin ID to the master metadata bin."""
        with self._lock:
            if not JSONBIN_API_KEY:
                return False
            
            # Get current data
            data = self.get_bin_ids()
            data[bin_name] = bin_id
            
            # If we don't have a master bin yet, create one
            if not self.bin_id:
                return self._create_master_bin(data)
            
            # Update existing master bin
            try:
                url = f"{JSONBIN_API_BASE}/b/{self.bin_id}"
                response = requests.put(url, json=data, headers=self._get_headers(), timeout=10)
                
                if response.status_code == 200:
                    self._cache = data
                    logger.debug(f"Updated master bin with {bin_name} = {bin_id}")
                    return True
                else:
                    logger.error(f"Failed to update master bin: {response.status_code}")
                    return False
            except Exception as e:
                logger.error(f"Error updating master bin: {e}")
                return False
    
    def _create_master_bin(self, data: dict) -> bool:
        """Create the master metadata bin."""
        try:
            url = f"{JSONBIN_API_BASE}/b"
            headers = self._get_headers()
            headers["X-Bin-Name"] = MASTER_BIN_NAME
            
            response = requests.post(url, json=data, headers=headers, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                self.bin_id = result.get("metadata", {}).get("id")
                self._cache = data
                
                logger.info(f"✅ Created master metadata bin with ID: {self.bin_id}")
                logger.info(f"📝 Add to your .env.local: JSONBIN_MASTER_BIN_ID={self.bin_id}")
                return True
            else:
                logger.error(f"Failed to create master bin: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error creating master bin: {e}")
            return False
    
    def clear_cache(self):
        with self._lock:
            self._cache = None


# Global master bin manager
_master_bin_manager = None


def _get_master_bin_manager() -> MasterBinManager:
    global _master_bin_manager
    if _master_bin_manager is None:
        _master_bin_manager = MasterBinManager()
    return _master_bin_manager


class JSONBinStorage:
    """
    A storage class that uses JSONBin.io for cloud storage with auto-creation.
    Bin IDs are stored in a master metadata bin, so no environment variables
    are needed except the API key.
    
    Features:
    - Automatic bin creation on JSONBin.io if bin doesn't exist
    - Bin IDs stored in master metadata bin (no env vars needed)
    - In-memory caching to reduce API calls
    - Local file fallback when API is unavailable
    - Thread-safe operations
    """
    
    def __init__(self, bin_name: str, local_path: str, default_value: Any):
        """
        Initialize a JSONBin storage instance.
        
        Args:
            bin_name: Friendly name for the bin (used as unique identifier)
            local_path: Path to local fallback file
            default_value: Default value if no data exists
        """
        self.bin_name = bin_name
        self.bin_id = None
        self.local_path = local_path
        self.default_value = default_value
        self._cache = None
        self._lock = threading.Lock()
        self._use_local_only = not JSONBIN_API_KEY
        self._bin_created = False
        self._creation_attempted = False
        
        # Ensure local directory exists
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
    
    def _get_headers(self) -> dict:
        """Get headers for JSONBin.io API requests."""
        return {
            "Content-Type": "application/json",
            "X-Master-Key": JSONBIN_API_KEY
        }
    
    def _read_local(self) -> Any:
        """Read data from local fallback file."""
        try:
            if os.path.exists(self.local_path):
                with open(self.local_path, "r") as f:
                    return json.load(f)
        except Exception as e:
            logger.debug(f"Failed to read local file {self.local_path}: {e}")
        return None
    
    def _write_local(self, data: Any) -> None:
        """Write data to local fallback file."""
        try:
            os.makedirs(os.path.dirname(self.local_path), exist_ok=True)
            with open(self.local_path, "w") as f:
                json.dump(data, f)
        except Exception as e:
            logger.error(f"Failed to write local file {self.local_path}: {e}")
    
    def _ensure_bin_exists(self) -> bool:
        """
        Ensure the bin exists on JSONBin.io.
        First checks the master metadata bin for the bin ID.
        If not found, creates a new bin and registers it.
        
        Returns:
            True if bin exists or was created successfully
        """
        if self._use_local_only:
            return False
            
        if self.bin_id and self._bin_created:
            return True
        
        # Check master bin for existing bin ID
        if not self.bin_id and not self._creation_attempted:
            master = _get_master_bin_manager()
            bin_ids = master.get_bin_ids()
            if self.bin_name in bin_ids:
                self.bin_id = bin_ids[self.bin_name]
                self._bin_created = True
                logger.debug(f"Found bin '{self.bin_name}' with ID: {self.bin_id}")
                return True
        
        # Try to create new bin
        if not self.bin_id:
            return self._create_bin()
        
        return True
    
    def _create_bin(self) -> bool:
        """
        Create a new bin on JSONBin.io with the default data.
        Registers the new bin ID in the master metadata bin.
        
        Returns:
            True if creation was successful
        """
        if self._creation_attempted:
            return self.bin_id is not None
            
        self._creation_attempted = True
        
        try:
            url = f"{JSONBIN_API_BASE}/b"
            headers = self._get_headers()
            headers["X-Bin-Name"] = self.bin_name
            
            response = requests.post(
                url,
                json=self.default_value,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                self.bin_id = result.get("metadata", {}).get("id")
                self._bin_created = True
                
                # Register in master bin
                master = _get_master_bin_manager()
                if master.save_bin_id(self.bin_name, self.bin_id):
                    logger.info(f"✅ Created JSONBin '{self.bin_name}' with ID: {self.bin_id}")
                else:
                    logger.warning(f"Created bin but failed to register in master bin")
                
                return True
            else:
                logger.error(f"Failed to create bin '{self.bin_name}': {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error creating bin '{self.bin_name}': {e}")
            return False
    
    def read(self, use_cache: bool = True) -> Any:
        """
        Read data from storage.
        
        Args:
            use_cache: Whether to use cached data if available
            
        Returns:
            The stored data or default value
        """
        with self._lock:
            # Return cached data if available and allowed
            if use_cache and self._cache is not None:
                return self._cache
            
            # Try JSONBin.io first if configured
            if not self._use_local_only:
                # Ensure bin exists (create if needed)
                if self._ensure_bin_exists() and self.bin_id:
                    try:
                        url = f"{JSONBIN_API_BASE}/b/{self.bin_id}/latest"
                        headers = self._get_headers()
                        headers["X-Bin-Meta"] = "false"  # Get just the data, no metadata
                        
                        response = requests.get(url, headers=headers, timeout=10)
                        
                        if response.status_code == 200:
                            result = response.json()
                            self._cache = result
                            return result
                        elif response.status_code == 404:
                            logger.warning(f"Bin '{self.bin_name}' not found, falling back to local")
                            self.bin_id = None
                            self._bin_created = False
                    except Exception as e:
                        logger.warning(f"JSONBin.io read error for '{self.bin_name}', falling back to local: {e}")
            
            # Fall back to local storage
            local_data = self._read_local()
            if local_data is not None:
                self._cache = local_data
                return local_data
            
            # Return default value
            self._cache = self.default_value
            return self.default_value
    
    def write(self, data: Any) -> bool:
        """
        Write data to storage.
        
        Args:
            data: The data to store
            
        Returns:
            True if write was successful
        """
        with self._lock:
            # Update cache
            self._cache = data
            
            # Always write to local fallback
            self._write_local(data)
            
            # Try JSONBin.io if configured
            if not self._use_local_only:
                # Ensure bin exists (create if needed)
                if not self._ensure_bin_exists() or not self.bin_id:
                    logger.warning(f"Could not ensure bin exists for '{self.bin_name}', using local only")
                    return True  # Local write succeeded
                
                try:
                    url = f"{JSONBIN_API_BASE}/b/{self.bin_id}"
                    response = requests.put(
                        url, 
                        json=data, 
                        headers=self._get_headers(),
                        timeout=10
                    )
                    
                    if response.status_code == 200:
                        logger.debug(f"Successfully wrote to JSONBin '{self.bin_name}' ({self.bin_id})")
                        return True
                    elif response.status_code == 404:
                        # Bin doesn't exist anymore, try to recreate
                        logger.warning(f"Bin '{self.bin_name}' not found during write, recreating...")
                        self.bin_id = None
                        self._bin_created = False
                        if self._create_bin():
                            # Retry write with new bin
                            return self.write(data)
                        return False
                    else:
                        logger.warning(f"JSONBin write failed for '{self.bin_name}': {response.status_code} - {response.text}")
                        return False
                except Exception as e:
                    logger.warning(f"JSONBin.io write error for '{self.bin_name}', using local only: {e}")
                    return True  # Local write succeeded
            
            return True
    
    def clear_cache(self) -> None:
        """Clear the in-memory cache."""
        with self._lock:
            self._cache = None


# Create storage instances for each data type
_activated_chats_storage = None
_doorman_chats_storage = None
_activation_requests_storage = None


def _get_activated_chats_storage() -> JSONBinStorage:
    """Get or create the activated chats storage instance."""
    global _activated_chats_storage
    if _activated_chats_storage is None:
        _activated_chats_storage = JSONBinStorage(
            bin_name="activated_chats",
            local_path=LOCAL_ACTIVATED_CHATS,
            default_value=[]
        )
    return _activated_chats_storage


def _get_doorman_chats_storage() -> JSONBinStorage:
    """Get or create the doorman chats storage instance."""
    global _doorman_chats_storage
    if _doorman_chats_storage is None:
        _doorman_chats_storage = JSONBinStorage(
            bin_name="doorman_chats",
            local_path=LOCAL_DOORMAN_CHATS,
            default_value=[]
        )
    return _doorman_chats_storage


def _get_activation_requests_storage() -> JSONBinStorage:
    """Get or create the activation requests storage instance."""
    global _activation_requests_storage
    if _activation_requests_storage is None:
        _activation_requests_storage = JSONBinStorage(
            bin_name="activation_requests",
            local_path=LOCAL_ACTIVATION_REQUESTS,
            default_value=[]
        )
    return _activation_requests_storage


# Public API functions matching the original interface
def load_activated_chats() -> set[int]:
    """Load activated chats from storage."""
    data = _get_activated_chats_storage().read()
    return set(data) if isinstance(data, list) else set()


def save_activated_chats(chats: set[int]) -> None:
    """Save activated chats to storage."""
    _get_activated_chats_storage().write(list(chats))


def load_doorman_chats() -> set[int]:
    """Load doorman chats from storage."""
    data = _get_doorman_chats_storage().read()
    return set(data) if isinstance(data, list) else set()


def save_doorman_chats(chats: set[int]) -> None:
    """Save doorman chats to storage."""
    _get_doorman_chats_storage().write(list(chats))


def load_activation_requests() -> list[dict]:
    """Load activation requests from storage."""
    data = _get_activation_requests_storage().read()
    return data if isinstance(data, list) else []


def save_activation_requests(requests: list[dict]) -> None:
    """Save activation requests to storage."""
    _get_activation_requests_storage().write(requests)


def clear_all_caches() -> None:
    """Clear all in-memory caches. Useful for testing or forcing a refresh."""
    if _activated_chats_storage:
        _activated_chats_storage.clear_cache()
    if _doorman_chats_storage:
        _doorman_chats_storage.clear_cache()
    if _activation_requests_storage:
        _activation_requests_storage.clear_cache()
    if _master_bin_manager:
        _master_bin_manager.clear_cache()


def get_storage_info() -> dict:
    """
    Get information about all storage bins.
    Useful for logging or debugging.
    
    Returns:
        Dictionary with bin names and their IDs
    """
    info = {
        "master_bin_id": _get_master_bin_manager().bin_id if _master_bin_manager else None,
        "bins": {}
    }
    
    for name, storage in [
        ("activated_chats", _get_activated_chats_storage()),
        ("doorman_chats", _get_doorman_chats_storage()),
        ("activation_requests", _get_activation_requests_storage()),
    ]:
        info["bins"][name] = storage.bin_id
    
    return info