"""Button entities for Tesla Vehicle Command."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import TeslaVehicleCommandCoordinator
from .entity import TeslaVehicleCommandEntity

BUTTON_DESCRIPTIONS = [
    ButtonEntityDescription(
        key="wake_up",
        name="Wake Up",
        icon="mdi:car-wake",
    ),
    ButtonEntityDescription(
        key="honk_horn",
        name="Honk Horn",
        icon="mdi:bullhorn",
    ),
    ButtonEntityDescription(
        key="flash_lights",
        name="Flash Lights",
        icon="mdi:car-light-high",
    ),
    ButtonEntityDescription(
        key="open_charge_port",
        name="Open Charge Port",
        icon="mdi:ev-plug-ccs2",
    ),
    ButtonEntityDescription(
        key="close_charge_port",
        name="Close Charge Port",
        icon="mdi:ev-plug-ccs2-off",
    ),
    ButtonEntityDescription(
        key="open_trunk",
        name="Open Trunk",
        icon="mdi:car-back",
    ),
    ButtonEntityDescription(
        key="open_frunk",
        name="Open Frunk",
        icon="mdi:car-front",
    ),
    ButtonEntityDescription(
        key="vent_windows",
        name="Vent Windows",
        icon="mdi:window-open-variant",
    ),
    ButtonEntityDescription(
        key="close_windows",
        name="Close Windows",
        icon="mdi:window-closed",
    ),
    ButtonEntityDescription(
        key="preconditioning_start",
        name="Start Battery Preconditioning",
        icon="mdi:battery-charging",
    ),
    ButtonEntityDescription(
        key="preconditioning_stop",
        name="Stop Battery Preconditioning",
        icon="mdi:battery-off",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities."""
    coordinator: TeslaVehicleCommandCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities = []
    for vehicle in coordinator.vehicles:
        vin = vehicle["vin"]
        for description in BUTTON_DESCRIPTIONS:
            entities.append(TeslaButtonEntity(coordinator, vin, vehicle["name"], description))

    async_add_entities(entities)


class TeslaButtonEntity(TeslaVehicleCommandEntity, ButtonEntity):
    """Button entity for Tesla vehicle commands."""

    def __init__(
        self,
        coordinator: TeslaVehicleCommandCoordinator,
        vin: str,
        vehicle_name: str,
        description: ButtonEntityDescription,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator, vin, vehicle_name)
        self.entity_description = description
        self._attr_unique_id = f"{vin}_{description.key}"
        self._attr_name = f"{vehicle_name} {description.name}"

    async def async_press(self) -> None:
        """Handle button press."""
        key = self.entity_description.key

        # Map button keys to commands
        command_map = {
            "wake_up": ("wake_up", {}),
            "honk_horn": ("honk", {}),
            "flash_lights": ("flash", {}),
            "open_charge_port": ("charge_port_open", {}),
            "close_charge_port": ("charge_port_close", {}),
            "open_trunk": ("trunk_rear", {}),
            "open_frunk": ("trunk_front", {}),
            "vent_windows": ("window_vent", {}),
            "close_windows": ("window_close", {}),
            "preconditioning_start": ("climate_on", {}),
            "preconditioning_stop": ("climate_off", {}),
        }

        if key not in command_map:
            return

        command, body = command_map[key]

        try:
            if key == "wake_up":
                await self.coordinator.async_wake_up(self.vin)
            else:
                await self.coordinator.async_send_command(self.vin, command, body)

            # Request refresh
            await self.coordinator.async_request_refresh()
        except Exception as err:
            self._attr_available = False
            raise
