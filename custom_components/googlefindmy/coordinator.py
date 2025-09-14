"""Data coordinator for Google Find My Device."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
import time

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import slugify

from .const import DOMAIN, UPDATE_INTERVAL
from .api import GoogleFindMyAPI
from .location_recorder import LocationRecorder
from .Auth.fcm_receiver_ha import FcmReceiverHA

_LOGGER = logging.getLogger(__name__)

class GoogleFindMyCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Google Find My Device data."""

    def __init__(self, hass: HomeAssistant, oauth_token: str = None, google_email: str = None, secrets_data: dict = None, tracked_devices: list = None, location_poll_interval: int = 300, device_poll_delay: int = 5, min_poll_interval: int = 60) -> None:
        """Initialize."""
        if secrets_data:
            self.api = GoogleFindMyAPI(secrets_data=secrets_data)
        else:
            self.api = GoogleFindMyAPI(oauth_token=oauth_token, google_email=google_email)

        self.tracked_devices = tracked_devices or []
        self.location_poll_interval = max(location_poll_interval, min_poll_interval)
        self.device_poll_delay = device_poll_delay
        self.min_poll_interval = min_poll_interval

        self._device_location_data = {}
        self._last_location_poll_time = 0
        self._device_names = {}

        self.location_recorder = LocationRecorder(hass)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.fcm_receiver = FcmReceiverHA()
        self._fcm_initialized = False

    async def _async_initialize_fcm(self):
        """Initialize the FCM receiver."""
        if not self._fcm_initialized:
            if await self.fcm_receiver.async_initialize():
                self.fcm_receiver.register_coordinator(self)
                self._fcm_initialized = True
            else:
                _LOGGER.error("Failed to initialize FCM receiver.")

    async def _async_shutdown(self):
        """Stop the FCM listener when the integration is unloaded."""
        if self._fcm_initialized:
            await self.fcm_receiver.async_stop()
            self._fcm_initialized = False
            _LOGGER.info("Google Find My Device FCM listener shut down.")

    async def _async_update_data(self):
        """Update data via library."""
        try:
            if not self._fcm_initialized:
                await self._async_initialize_fcm()

            all_devices = await self.hass.async_add_executor_job(self.api.get_basic_device_list)

            if self.tracked_devices:
                devices = [dev for dev in all_devices if dev["id"] in self.tracked_devices]
            else:
                devices = all_devices

            for device in devices:
                self._device_names[device["id"]] = device["name"]

            current_time = time.time()
            time_since_last_poll = current_time - self._last_location_poll_time
            should_poll_location = (time_since_last_poll >= self.location_poll_interval)

            if self._last_location_poll_time == 0:
                should_poll_location = False
                self._last_location_poll_time = current_time

            if should_poll_location and devices:
                _LOGGER.debug("Starting location poll for %d devices", len(devices))
                for i, device in enumerate(devices):
                    device_id = device["id"]
                    device_name = device["name"]

                    if i > 0:
                        await asyncio.sleep(self.device_poll_delay)

                    try:
                        _LOGGER.debug(f"Requesting location for {device_name}")
                        location_data = await self.api.async_get_device_location(device_id, device_name)

                        if location_data:
                            config_data = self.hass.data.get(DOMAIN, {}).get("config_data", {})
                            min_accuracy_threshold = config_data.get("min_accuracy_threshold", 100)

                            if (location_data.get('latitude') is not None and location_data.get('longitude') is not None) or location_data.get('semantic_name'):
                                if location_data.get('accuracy') is not None and location_data.get('accuracy') > min_accuracy_threshold:
                                    _LOGGER.debug(f"Filtering out location for {device_name}: accuracy {location_data.get('accuracy')}m exceeds threshold {min_accuracy_threshold}m")
                                else:
                                    # Use a consistent entity ID for history lookup
                                    entity_id = f"device_tracker.{DOMAIN}_{slugify(device_id)}"
                                    
                                    historical_locations = await self.location_recorder.get_location_history(entity_id, hours=24)

                                    current_location_entry = {
                                        'timestamp': location_data.get('last_seen', current_time),
                                        'latitude': location_data.get('latitude'),
                                        'longitude': location_data.get('longitude'),
                                        'accuracy': location_data.get('accuracy'),
                                        'semantic_name': location_data.get('semantic_name'),
                                        'is_own_report': location_data.get('is_own_report', False),
                                        'altitude': location_data.get('altitude')
                                    }
                                    historical_locations.insert(0, current_location_entry)

                                    best_location = self.location_recorder.get_best_location(historical_locations)

                                    if best_location:
                                        self._device_location_data[device_id] = {**location_data, **best_location}
                                        self._device_location_data[device_id]["last_updated"] = current_time
                        else:
                            _LOGGER.warning(f"No location data returned for {device_name}")

                    except Exception as e:
                        _LOGGER.error(f"Failed to get location for {device_name}: {e}")

                self._last_location_poll_time = current_time

            # Combine basic device info with latest location data
            final_device_data = []
            for device in devices:
                device_id = device["id"]
                
                # Start with the basic device info
                device_info = device.copy()
                
                # Update with the latest cached location data if it exists
                if device_id in self._device_location_data:
                    device_info.update(self._device_location_data[device_id])

                final_device_data.append(device_info)

            return final_device_data

        except Exception as exception:
            raise UpdateFailed(exception) from exception

    async def async_locate_device(self, device_id: str) -> dict:
        """Locate a device."""
        return await self.hass.async_add_executor_job(
            self.api.locate_device, device_id
        )

    async def async_play_sound(self, device_id: str) -> bool:
        """Play sound on a device."""
        return await self.hass.async_add_executor_job(
            self.api.play_sound, device_id
        )