"""API wrapper for Google Find My Device."""
from __future__ import annotations

import logging
from typing import Any

from custom_components.googlefindmy.Auth.token_cache import save_oauth_token, load_oauth_token
from custom_components.googlefindmy.NovaApi.ListDevices.nbe_list_devices import request_device_list
from custom_components.googlefindmy.NovaApi.ExecuteAction.LocateTracker.location_request import get_location_data_for_device
from custom_components.googlefindmy.NovaApi.ExecuteAction.PlaySound.start_sound_request import start_sound_request
from custom_components.googlefindmy.NovaApi.nova_request import nova_request
from custom_components.googlefindmy.NovaApi.scopes import NOVA_ACTION_API_SCOPE
from custom_components.googlefindmy.ProtoDecoders.decoder import parse_device_list_protobuf, get_canonic_ids, get_devices_with_location
# Import FcmReceiver lazily to avoid protobuf conflicts

_LOGGER = logging.getLogger(__name__)


class GoogleFindMyAPI:
    """API wrapper for Google Find My Device."""

    def __init__(self, oauth_token: str = None, google_email: str = None, secrets_data: dict = None) -> None:
        """Initialize the API wrapper."""
        if secrets_data:
            # Use secrets.json data from original GoogleFindMyTools
            self._initialize_from_secrets(secrets_data)
        else:
            # Use individual tokens
            self.oauth_token = oauth_token
            self.google_email = google_email
            # Cache the token and email in memory to avoid file I/O
            from custom_components.googlefindmy.Auth.token_cache import set_memory_cache
            from custom_components.googlefindmy.Auth.username_provider import username_string
            
            # Create memory cache with individual tokens
            cache_data = {
                "oauth_token": oauth_token,
                username_string: google_email
            }
            set_memory_cache(cache_data)
    
    def _initialize_from_secrets(self, secrets_data: dict) -> None:
        """Initialize from secrets.json data."""
        from custom_components.googlefindmy.Auth.username_provider import username_string
        from custom_components.googlefindmy.Auth.token_cache import set_memory_cache
        
        # Store secrets data in memory cache to avoid file I/O in event loop
        enhanced_data = secrets_data.copy()
        
        # Extract common values
        self.google_email = secrets_data.get('username', secrets_data.get('Email'))
        
        # Store username for later use
        if self.google_email:
            enhanced_data[username_string] = self.google_email
            
        # Set the memory cache for the token system to use
        set_memory_cache(enhanced_data)
        
        # Note: Persistent cache saving removed from sync init to avoid blocking I/O
        # The memory cache will be used during this session, and async saving will happen later
        _LOGGER.debug(f"Loaded {len(enhanced_data)} items into memory cache")
    
    def get_basic_device_list(self) -> list[dict[str, Any]]:
        """Get list of Find My devices without location data (for config flow)."""
        try:
            result_hex = request_device_list()
            device_list = parse_device_list_protobuf(result_hex)
            canonic_ids = get_canonic_ids(device_list)
            
            devices = []
            for device_name, canonic_id in canonic_ids:
                devices.append({
                    "name": device_name,
                    "id": canonic_id,
                    "device_id": canonic_id,
                })
            
            return devices
        except Exception as err:
            _LOGGER.error("Failed to get basic device list: %s", err)
            raise

    def get_devices(self) -> list[dict[str, Any]]:
        """Get list of Find My devices with basic info (no location data for now)."""
        try:
            _LOGGER.info("API v3.0: Getting basic device list only (location data requires individual requests)")
            result_hex = request_device_list()
            device_list = parse_device_list_protobuf(result_hex)
            canonic_ids = get_canonic_ids(device_list)
            
            devices = []
            for device_name, canonic_id in canonic_ids:
                device_info = {
                    "name": device_name,
                    "id": canonic_id,
                    "device_id": canonic_id,
                    "latitude": None,
                    "longitude": None,
                    "altitude": None,
                    "accuracy": None,
                    "last_seen": None,
                    "status": "No location data (requires individual request)",
                    "is_own_report": None,
                    "semantic_name": None,
                    "battery_level": None
                }
                devices.append(device_info)
            
            _LOGGER.info(f"API v3.0: Returning {len(devices)} devices with basic info")
            return devices
        except Exception as err:
            _LOGGER.error("Failed to get devices: %s", err)
            import traceback
            _LOGGER.error("Traceback: %s", traceback.format_exc())
            raise

    def get_device_location(self, device_id: str, device_name: str) -> dict[str, Any]:
        """Get location data for a specific device using individual request."""
        try:
            _LOGGER.info(f"API v3.0: Requesting location for device {device_name} ({device_id})")
            
            # Use the original location request approach
            _LOGGER.info(f"DEBUG: About to call get_location_data_for_device for {device_name}")
            location_data = get_location_data_for_device(device_id, device_name)
            _LOGGER.info(f"DEBUG: get_location_data_for_device returned: {location_data}")
            
            if location_data and len(location_data) > 0:
                _LOGGER.info(f"API v3.0: Got {len(location_data)} location records for {device_name}")
                # Return the most recent location
                return location_data[0]
            else:
                _LOGGER.warning(f"API v3.0: No location data returned for {device_name}")
                return {}
                
        except Exception as err:
            _LOGGER.error("Failed to get location for device %s (%s): %s", device_name, device_id, err)
            import traceback
            _LOGGER.error("Traceback: %s", traceback.format_exc())
            return {}

    async def async_get_device_location(self, device_id: str, device_name: str) -> dict[str, Any]:
        """Get location data for a specific device using async HA-compatible request."""
        try:
            _LOGGER.info(f"API v3.0 Async: Requesting location for device {device_name} ({device_id})")
            
            # Use the async location request approach
            location_data = await get_location_data_for_device(device_id, device_name)
            
            if location_data and len(location_data) > 0:
                _LOGGER.info(f"API v3.0 Async: Got {len(location_data)} location records for {device_name}")
                # Return the most recent location
                return location_data[0]
            else:
                _LOGGER.warning(f"API v3.0 Async: No location data returned for {device_name}")
                return {}
                
        except Exception as err:
            _LOGGER.error("Failed to get async location for device %s (%s): %s", device_name, device_id, err)
            import traceback
            _LOGGER.error("Traceback: %s", traceback.format_exc())
            return {}

    def locate_device(self, device_id: str) -> dict[str, Any]:
        """Get location data for a device."""
        try:
            # Find device name from ID (simplified for now)
            device_name = device_id  # This should be improved
            location_data = get_location_data_for_device(device_id, device_name)
            return location_data
        except Exception as err:
            _LOGGER.error("Failed to locate device %s: %s", device_id, err)
            raise

    def play_sound(self, device_id: str) -> bool:
        """Play sound on a device."""
        try:
            # Get FCM token from the HA-compatible receiver
            from custom_components.googlefindmy.Auth.fcm_receiver_ha import FcmReceiverHA
            fcm_receiver = FcmReceiverHA()
            
            # Initialize FCM receiver if needed
            if not fcm_receiver.credentials:
                _LOGGER.error("FCM receiver not initialized for play sound - credentials missing")
                return False
            
            fcm_token = fcm_receiver.get_fcm_token()
            if not fcm_token:
                _LOGGER.error("No FCM token available for play sound - token is None or empty")
                return False
            
            _LOGGER.debug(f"FCM receiver status: credentials={bool(fcm_receiver.credentials)}, token_length={len(fcm_token) if fcm_token else 0}")
            
            _LOGGER.info(f"Playing sound on device {device_id} with FCM token {fcm_token[:20]}...")
            
            # Create and send sound request
            hex_payload = start_sound_request(device_id, fcm_token)
            _LOGGER.info(f"Sound request payload length: {len(hex_payload)} chars")
            _LOGGER.debug(f"Sound request payload: {hex_payload[:100]}...")
            
            result = nova_request(NOVA_ACTION_API_SCOPE, hex_payload)
            _LOGGER.debug(f"nova_request result for sound: '{result}' (length: {len(result) if result is not None else 'None'})")
            
            # For sound requests, Google returns empty response on success (HTTP 200 with no body)
            # nova_request returns empty string for successful 200 responses with no content
            if result is not None:  # Check if nova_request completed without exception
                _LOGGER.info(f"Sound request sent successfully for device {device_id}")
                return True
            else:
                _LOGGER.error(f"Sound request failed for device {device_id} - nova_request returned None (API error)")
                return False
                
        except Exception as err:
            _LOGGER.error("Failed to play sound on device %s: %s", device_id, err)
            return False