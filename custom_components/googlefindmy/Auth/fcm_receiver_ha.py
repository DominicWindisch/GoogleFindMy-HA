"""Home Assistant compatible FCM receiver for Google Find My Device."""
import asyncio
import base64
import binascii
import logging
from typing import Optional, Callable, Dict, Any

from custom_components.googlefindmy.Auth.token_cache import (
    set_cached_value,
    get_cached_value,
    async_set_cached_value,
    async_get_cached_value,
    async_load_cache_from_file
)

_LOGGER = logging.getLogger(__name__)


class FcmReceiverHA:
    """FCM Receiver that works with Home Assistant's async architecture."""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(FcmReceiverHA, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        """Initialize the FCM receiver for Home Assistant."""
        if hasattr(self, '_initialized') and self._initialized:
            return
        self._initialized = True

        self.credentials = None
        self.location_update_callbacks: Dict[str, Callable] = {}
        self.coordinators = []  # List of coordinators that can receive background updates
        self.pc = None

        # Firebase project configuration for Google Find My Device
        self.project_id = "google.com:api-project-289722593072"
        self.app_id = "1:289722593072:android:3cfcf5bc359f0308"
        self.api_key = "AIzaSyD_gko3P392v6how2H7UpdeXQ0v2HLettc"
        self.message_sender_id = "289722593072"

    async def async_initialize(self):
        """Async initialization that works with Home Assistant."""
        try:
            # Load cached credentials asynchronously to avoid blocking I/O
            await async_load_cache_from_file()
            self.credentials = await async_get_cached_value('fcm_credentials')

            if isinstance(self.credentials, str):
                import json
                try:
                    self.credentials = json.loads(self.credentials)
                    _LOGGER.debug("Parsed FCM credentials from JSON string")
                except json.JSONDecodeError as e:
                    _LOGGER.error(f"Failed to parse FCM credentials JSON: {e}")
                    return False

            from custom_components.googlefindmy.Auth.firebase_messaging import FcmRegisterConfig, FcmPushClient

            fcm_config = FcmRegisterConfig(
                project_id=self.project_id,
                app_id=self.app_id,
                api_key=self.api_key,
                messaging_sender_id=self.message_sender_id,
                bundle_id="com.google.android.apps.adm",
            )

            self.pc = FcmPushClient(
                self._on_notification,
                fcm_config,
                self.credentials,
                self._on_credentials_updated
            )

            _LOGGER.info("FCM receiver initialized successfully")
            return True

        except Exception as e:
            _LOGGER.error(f"Failed to initialize FCM receiver: {e}")
            return False

    async def async_register_for_location_updates(self, device_id: str, callback: Callable) -> Optional[str]:
        """Register for location updates asynchronously."""
        try:
            self.location_update_callbacks[device_id] = callback
            _LOGGER.debug(f"Registered FCM callback for device: {device_id}")

            if not self.pc or not self.pc.is_started():
                await self._start_listening()

            if self.credentials and 'fcm' in self.credentials and 'registration' in self.credentials['fcm']:
                token = self.credentials['fcm']['registration']['token']
                _LOGGER.info(f"FCM token available: {token[:20]}...")
                return token
            else:
                _LOGGER.warning("FCM credentials not available")
                return None

        except Exception as e:
            _LOGGER.error(f"Failed to register for location updates: {e}")
            return None

    async def async_unregister_for_location_updates(self, device_id: str) -> None:
        """Unregister a device from location updates."""
        try:
            if device_id in self.location_update_callbacks:
                del self.location_update_callbacks[device_id]
                _LOGGER.debug(f"Unregistered FCM callback for device: {device_id}")
            else:
                _LOGGER.debug(f"No FCM callback found to unregister for device: {device_id}")
        except Exception as e:
            _LOGGER.error(f"Failed to unregister location updates for {device_id}: {e}")

    def register_coordinator(self, coordinator) -> None:
        """Register a coordinator to receive background location updates."""
        if coordinator not in self.coordinators:
            self.coordinators.append(coordinator)
            _LOGGER.debug("Registered coordinator for background FCM updates")

    def unregister_coordinator(self, coordinator) -> None:
        """Unregister a coordinator from background location updates."""
        if coordinator in self.coordinators:
            self.coordinators.remove(coordinator)
            _LOGGER.debug("Unregistered coordinator from background FCM updates")

    async def _start_listening(self):
        """Start listening for FCM messages."""
        try:
            if not self.pc:
                await self.async_initialize()

            if self.pc:
                await self._register_for_fcm()
                asyncio.create_task(self._listen_for_messages())
                _LOGGER.info("Started listening for FCM notifications")
            else:
                _LOGGER.error("Failed to create FCM push client")

        except Exception as e:
            _LOGGER.error(f"Failed to start FCM listening: {e}")

    async def _register_for_fcm(self):
        """Register with FCM to get token."""
        if not self.pc:
            return

        fcm_token = None
        retries = 0

        while fcm_token is None and retries < 3:
            try:
                fcm_token = await self.pc.checkin_or_register()
                if fcm_token:
                    _LOGGER.info(f"FCM registration successful, token: {fcm_token[:20]}...")
                else:
                    _LOGGER.warning(f"FCM registration attempt {retries + 1} failed")
                    retries += 1
                    await asyncio.sleep(5)
            except Exception as e:
                _LOGGER.error(f"FCM registration error: {e}")
                retries += 1
                await asyncio.sleep(5)

    async def _listen_for_messages(self):
        """Listen for FCM messages in background."""
        try:
            if self.pc:
                await self.pc.start()
                _LOGGER.info("FCM message listener started")
        except Exception as e:
            _LOGGER.error(f"FCM listen error: {e}")

    def _on_notification(self, obj: Dict[str, Any], notification, data_message):
        """Handle incoming FCM notification."""
        try:
            if 'data' in obj and 'com.google.android.apps.adm.FCM_PAYLOAD' in obj['data']:
                base64_string = obj['data']['com.google.android.apps.adm.FCM_PAYLOAD']

                missing_padding = len(base64_string) % 4
                if missing_padding:
                    base64_string += '=' * (4 - missing_padding)

                try:
                    decoded_bytes = base64.b64decode(base64_string)
                except Exception as decode_error:
                    _LOGGER.error(f"FCM Base64 decode failed in _on_notification: {decode_error}")
                    _LOGGER.debug(f"Problematic Base64 string (length={len(base64_string)}): {base64_string[:50]}...")
                    return

                hex_string = binascii.hexlify(decoded_bytes).decode('utf-8')
                _LOGGER.info(f"Received FCM location response: {len(hex_string)} chars")

                canonic_id = None
                try:
                    canonic_id = self._extract_canonic_id_from_response(hex_string)
                except Exception as extract_error:
                    _LOGGER.error(f"Failed to extract canonic_id from FCM response: {extract_error}")
                    return

                if canonic_id and canonic_id in self.location_update_callbacks:
                    callback = self.location_update_callbacks[canonic_id]
                    try:
                        asyncio.create_task(self._run_callback_async(callback, canonic_id, hex_string))
                    except Exception as e:
                        _LOGGER.error(f"Error scheduling FCM callback for device {canonic_id}: {e}")
                elif canonic_id:
                    handled_by_coordinator = False
                    for coordinator in self.coordinators:
                        if hasattr(coordinator, 'tracked_devices') and canonic_id in coordinator.tracked_devices:
                            _LOGGER.info(f"Processing background FCM update for tracked device {coordinator._device_names.get(canonic_id, canonic_id[:8])}")
                            asyncio.create_task(self._process_background_update(coordinator, canonic_id, hex_string))
                            handled_by_coordinator = True
                            break

                    if not handled_by_coordinator:
                        registered_count = len(self.location_update_callbacks)
                        if registered_count > 0:
                            registered_devices = list(self.location_update_callbacks.keys())
                            _LOGGER.debug(f"Received FCM response for untracked device {canonic_id[:8]}... "
                                        f"Currently waiting for: {[d[:8]+'...' for d in registered_devices]}")
                        else:
                            _LOGGER.debug(f"Received FCM response for untracked device {canonic_id[:8]}... "
                                        f"(not in any coordinator's tracked devices)")
                else:
                    _LOGGER.debug("Could not extract canonic_id from FCM response")
            else:
                _LOGGER.debug("FCM notification without location payload")

        except Exception as e:
            _LOGGER.error(f"Error processing FCM notification: {e}")

    def _extract_canonic_id_from_response(self, hex_response: str) -> Optional[str]:
        """Extract canonic_id from FCM response to identify which device sent it."""
        try:
            try:
                from custom_components.googlefindmy.ProtoDecoders.decoder import parse_device_update_protobuf
            except ImportError:
                from .ProtoDecoders.decoder import parse_device_update_protobuf

            device_update = parse_device_update_protobuf(hex_response)

            if (device_update.HasField("deviceMetadata") and
                device_update.deviceMetadata.identifierInformation.canonicIds.canonicId):
                return device_update.deviceMetadata.identifierInformation.canonicIds.canonicId[0].id
        except Exception as e:
            _LOGGER.debug(f"Failed to extract canonic_id from FCM response: {e}")
        return None

    async def _run_callback_async(self, callback, canonic_id: str, hex_string: str):
        """Run callback in executor to avoid blocking the event loop."""
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, callback, canonic_id, hex_string)
        except Exception as e:
            _LOGGER.error(f"Error in async FCM callback for device {canonic_id}: {e}")

    async def _process_background_update(self, coordinator, canonic_id: str, hex_string: str):
        """Process background FCM update for a tracked device."""
        try:
            import asyncio
            import time

            location_data = await asyncio.get_event_loop().run_in_executor(
                None, self._decode_background_location, hex_string
            )

            if location_data:
                coordinator._device_location_data[canonic_id] = location_data.copy()
                coordinator._device_location_data[canonic_id]["last_updated"] = time.time()

                device_name = coordinator._device_names.get(canonic_id, canonic_id[:8])
                _LOGGER.info(f"Stored background location update for {device_name}")

                await coordinator.async_request_refresh()
            else:
                _LOGGER.debug(f"No location data in background update for device {canonic_id}")

        except Exception as e:
            _LOGGER.error(f"Error processing background update for device {canonic_id}: {e}")

    def _decode_background_location(self, hex_string: str) -> dict:
        """Decode location data from hex string (runs in executor)."""
        try:
            try:
                from custom_components.googlefindmy.ProtoDecoders.decoder import parse_device_update_protobuf
                from custom_components.googlefindmy.NovaApi.ExecuteAction.LocateTracker.decrypt_locations import decrypt_location_response_locations
            except ImportError:
                try:
                    from ..ProtoDecoders.decoder import parse_device_update_protobuf
                    from ..NovaApi.ExecuteAction.LocateTracker.decrypt_locations import decrypt_location_response_locations
                except ImportError:
                    import sys
                    import os
                    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                    from ProtoDecoders.decoder import parse_device_update_protobuf
                    from NovaApi.ExecuteAction.LocateTracker.decrypt_locations import decrypt_location_response_locations

            device_update = parse_device_update_protobuf(hex_string)
            location_data = decrypt_location_response_locations(device_update)

            if location_data and len(location_data) > 0:
                return location_data[0]
            return {}

        except Exception as e:
            _LOGGER.error(f"Failed to decode background location data: {e}")
            return {}

    def _on_credentials_updated(self, creds):
        """Handle credential updates."""
        self.credentials = creds
        asyncio.create_task(self._async_save_credentials())
        _LOGGER.info("FCM credentials updated")

    async def _async_save_credentials(self):
        """Save credentials asynchronously."""
        try:
            await async_set_cached_value('fcm_credentials', self.credentials)
        except Exception as e:
            _LOGGER.error(f"Failed to save FCM credentials: {e}")

    async def async_stop(self):
        """Stop listening for FCM messages."""
        try:
            if self.pc:
                try:
                    if (hasattr(self.pc, 'stop') and callable(getattr(self.pc, 'stop')) and
                        hasattr(self.pc, 'stopping_lock') and self.pc.stopping_lock is not None):
                        await self.pc.stop()
                    else:
                        _LOGGER.debug("FCM push client not fully initialized, skipping stop")
                        self.pc = None
                except TypeError as type_error:
                    if "asynchronous context manager protocol" in str(type_error):
                        _LOGGER.debug(f"FCM push client stop method has context manager issue, skipping: {type_error}")
                    else:
                        _LOGGER.warning(f"Type error stopping FCM push client: {type_error}")
                except Exception as pc_error:
                    _LOGGER.debug(f"Error stopping FCM push client: {pc_error}")

            _LOGGER.info("FCM receiver stopped")

        except Exception as e:
            _LOGGER.error(f"Error stopping FCM receiver: {e}")

    def get_fcm_token(self) -> Optional[str]:
        """Get current FCM token if available."""
        if self.credentials and 'fcm' in self.credentials and 'registration' in self.credentials['fcm']:
            return self.credentials['fcm']['registration']['token']
        return None