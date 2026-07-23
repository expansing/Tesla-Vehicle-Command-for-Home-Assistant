"""Cover entities for Tesla Vehicle Command (trunk, frunk, windows, sunroof)."""

from __future__ import annotations

from homeassistant.components.cover import (
    CoverEntity,
    CoverEntityFeature,
    CoverDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import TeslaVehicleCommandCoordinator
from .entity import TeslaVehicleCommandEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up cover entities."""
    coordinator: TeslaVehicleCommandCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities = []
    for vehicle in coordinator.vehicles:
        vin = vehicle["vin"]
        entities.extend([
            TeslaTrunkEntity(coordinator, vin, vehicle["name"], "rear", "Trunk"),
            TeslaTrunkEntity(coordinator, vin, vehicle["name"], "front", "Frunk"),
            TeslaWindowsEntity(coordinator, vin, vehicle["name"]),
            TeslaSunroofEntity(coordinator, vin, vehicle["name"]),
        ])

    async_add_entities(entities)


class TeslaTrunkEntity(TeslaVehicleCommandEntity, CoverEntity):
    """Cover entity for Tesla trunk/frunk."""

    _attr_device_class = CoverDeviceClass.DOOR
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

    def __init__(
        self,
        coordinator: TeslaVehicleCommandCoordinator,
        vin: str,
        vehicle_name: str,
        trunk_type: str,
        name: str,
    ) -> None:
        """Initialize the trunk entity."""
        super().__init__(coordinator, vin, vehicle_name)
        self._trunk_type = trunk_type
        self._attr_unique_id = f"{vin}_{trunk_type}_trunk"
        self._attr_name = name

    @property
    def is_closed(self) -> bool | None:
        """Return true if closed."""
        vehicle_data = self.coordinator.data.get(self.vin, {})
        response = vehicle_data.get("response", {})
        vehicle_state = response.get("vehicle_state", {})

        if self._trunk_type == "rear":
            return not vehicle_state.get("trunk", False)
        else:
            return not vehicle_state.get("ft", False)

    @property
    def is_opening(self) -> bool:
        return False

    @property
    def is_closing(self) -> bool:
        return False

    async def async_open_cover(self, **kwargs) -> None:
        """Open the trunk/frunk."""
        command = "trunk_rear" if self._trunk_type == "rear" else "trunk_front"
        await self.coordinator.async_send_command(self.vin, command)
        await self.coordinator.async_request_refresh()

    async def async_close_cover(self, **kwargs) -> None:
        """Close the trunk (rear only - frunk cannot be closed remotely)."""
        if self._trunk_type == "rear":
            await self.coordinator.async_send_command(self.vin, "trunk_rear")
            await self.coordinator.async_request_refresh()


class TeslaWindowsEntity(TeslaVehicleCommandEntity, CoverEntity):
    """Cover entity for Tesla windows."""

    _attr_device_class = CoverDeviceClass.WINDOW
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

    def __init__(
        self,
        coordinator: TeslaVehicleCommandCoordinator,
        vin: str,
        vehicle_name: str,
    ) -> None:
        """Initialize the windows entity."""
        super().__init__(coordinator, vin, vehicle_name)
        self._attr_unique_id = f"{vin}_windows"
        self._attr_name = "Windows"

    @property
    def is_closed(self) -> bool | None:
        """Return true if all windows closed."""
        vehicle_data = self.coordinator.data.get(self.vin, {})
        response = vehicle_data.get("response", {})
        vehicle_state = response.get("vehicle_state", {})

        windows = [
            vehicle_state.get("fd_window"),
            vehicle_state.get("fp_window"),
            vehicle_state.get("rd_window"),
            vehicle_state.get("rp_window"),
        ]
        return all(w is not None and w <= 1 for w in windows)

    async def async_open_cover(self, **kwargs) -> None:
        """Vent windows."""
        await self.coordinator.async_send_command(self.vin, "window_vent")
        await self.coordinator.async_request_refresh()

    async def async_close_cover(self, **kwargs) -> None:
        """Close windows."""
        await self.coordinator.async_send_command(self.vin, "window_close")
        await self.coordinator.async_request_refresh()


class TeslaSunroofEntity(TeslaVehicleCommandEntity, CoverEntity):
    """Cover entity for Tesla sunroof."""

    _attr_device_class = CoverDeviceClass.WINDOW
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.SET_POSITION

    def __init__(
        self,
        coordinator: TeslaVehicleCommandCoordinator,
        vin: str,
        vehicle_name: str,
    ) -> None:
        """Initialize the sunroof entity."""
        super().__init__(coordinator, vin, vehicle_name)
        self._attr_unique_id = f"{vin}_sunroof"
        self._attr_name = "Sunroof"

    @property
    def current_cover_position(self) -> int | None:
        """Return current position (0-100)."""
        vehicle_data = self.coordinator.data.get(self.vin, {})
        response = vehicle_data.get("response", {})
        vehicle_state = response.get("vehicle_state", {})
        sunroof = vehicle_state.get("sun_roof_percent_open")
        if sunroof is not None:
            return int(sunroof)
        return None

    @property
    def is_closed(self) -> bool | None:
        pos = self.current_cover_position
        return pos == 0 if pos is not None else None

    async def async_open_cover(self, **kwargs) -> None:
        """Open sunroof."""
        await self.coordinator.async_send_command(self.vin, "sunroof", {"state": "open"})
        await self.coordinator.async_request_refresh()

    async def async_close_cover(self, **kwargs) -> None:
        """Close sunroof."""
        await self.coordinator.async_send_command(self.vin, "sunroof", {"state": "close"})
        await self.coordinator.async_request_refresh()

    async def async_set_cover_position(self, **kwargs) -> None:
        """Set sunroof position."""
        position = kwargs.get("position", 0)
        await self.coordinator.async_send_command(
            self.vin, "sunroof", {"state": "vent", "percent": position}
        )
        await self.coordinator.async_request_refresh()