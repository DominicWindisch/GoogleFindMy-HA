"""Button platform for Google Find My Device."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GoogleFindMyCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Google Find My Device button entities."""
    coordinator: GoogleFindMyCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = []
    if coordinator.data:
        for device in coordinator.data:
            entities.append(GoogleFindMyPlaySoundButton(coordinator, device))

    async_add_entities(entities, True)


class GoogleFindMyPlaySoundButton(CoordinatorEntity, ButtonEntity):
    """Representation of a Google Find My Device play sound button."""

    def __init__(
        self,
        coordinator: GoogleFindMyCoordinator,
        device: dict[str, Any],
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._device = device
        self._attr_unique_id = f"{DOMAIN}_{device['id']}_play_sound"
        self._attr_name = f"{device['name']} Play Sound"
        self._attr_icon = "mdi:volume-high"
        self._attr_has_entity_name = True

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._device["id"])},
            "name": self._device["name"],
            "manufacturer": "Google",
            "model": "Find My Device",
            "configuration_url": f"https://myaccount.google.com/device-activity?device_id={self._device['id']}",
            "hw_version": self._device["id"],
        }

    async def async_press(self) -> None:
        """Handle the button press."""
        device_id = self._device["id"]
        device_name = self._device["name"]
        
        _LOGGER.info(f"Play sound button pressed for {device_name} ({device_id})")
        
        try:
            result = await self.coordinator.async_play_sound(device_id)
            if result:
                _LOGGER.info(f"Successfully played sound on {device_name}")
            else:
                _LOGGER.warning(f"Failed to play sound on {device_name}")
        except Exception as err:
            _LOGGER.error(f"Error playing sound on {device_name}: {err}")