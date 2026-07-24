"""Sensor entities for Tesla Vehicle Command."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfLength,
    UnitOfTemperature,
    UnitOfElectricPotential,
    UnitOfElectricCurrent,
    UnitOfPower,
    UnitOfEnergy,
    UnitOfPressure,
    UnitOfSpeed,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import TeslaVehicleCommandCoordinator
from .entity import TeslaVehicleCommandEntity


@dataclass(frozen=True, kw_only=True)
class TeslaSensorEntityDescription(SensorEntityDescription):
    """Describes Tesla sensor entity."""

    value_path: str | None = None
    unit_path: str | None = None
    conversion: str | None = None
    value_map: dict[Any, str] | None = None


SENSOR_DESCRIPTIONS = [
    # Battery / Charging
    TeslaSensorEntityDescription(
        key="battery_level",
        name="Battery Level",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_path="charge_state.battery_level",
        icon="mdi:battery",
    ),
    TeslaSensorEntityDescription(
        key="battery_range",
        name="Battery Range",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        value_path="charge_state.battery_range",
        conversion="mi_to_km",
        icon="mdi:road",
    ),
    TeslaSensorEntityDescription(
        key="ideal_battery_range",
        name="Ideal Battery Range",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        value_path="charge_state.ideal_battery_range",
        conversion="mi_to_km",
        icon="mdi:road-variant",
    ),
    TeslaSensorEntityDescription(
        key="charging_state",
        name="Charging State",
        device_class=SensorDeviceClass.ENUM,
        options=["Charging", "Complete", "Disconnected", "Stopped", "NoPower"],
        value_path="charge_state.charging_state",
        icon="mdi:ev-station",
    ),
    TeslaSensorEntityDescription(
        key="charge_limit",
        name="Charge Limit",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_path="charge_state.charge_limit_soc",
        icon="mdi:battery-charging-50",
    ),
    TeslaSensorEntityDescription(
        key="charge_current",
        name="Charge Current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        value_path="charge_state.charge_current_request",
        icon="mdi:current-ac",
    ),
    TeslaSensorEntityDescription(
        key="charge_power",
        name="Charge Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        value_path="charge_state.charger_power",
        conversion="w_to_kw",
        icon="mdi:flash",
    ),
    TeslaSensorEntityDescription(
        key="charge_energy_added",
        name="Charge Energy Added",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_path="charge_state.charge_energy_added",
        conversion="wh_to_kwh",
        icon="mdi:battery-plus",
    ),
    TeslaSensorEntityDescription(
        key="time_to_full_charge",
        name="Time to Full Charge",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="h",
        value_path="charge_state.time_to_full_charge",
        icon="mdi:timer",
    ),

    # Climate
    TeslaSensorEntityDescription(
        key="inside_temp",
        name="Inside Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_path="climate_state.inside_temp",
        icon="mdi:thermometer",
    ),
    TeslaSensorEntityDescription(
        key="outside_temp",
        name="Outside Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_path="climate_state.outside_temp",
        icon="mdi:thermometer-lines",
    ),
    TeslaSensorEntityDescription(
        key="driver_temp_setting",
        name="Driver Temperature Setting",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_path="climate_state.driver_temp_setting",
        icon="mdi:thermostat",
    ),
    TeslaSensorEntityDescription(
        key="passenger_temp_setting",
        name="Passenger Temperature Setting",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_path="climate_state.passenger_temp_setting",
        icon="mdi:thermostat",
    ),
    TeslaSensorEntityDescription(
        key="is_climate_on",
        name="Climate On",
        device_class=SensorDeviceClass.ENUM,
        options=["On", "Off"],
        value_path="climate_state.is_climate_on",
        icon="mdi:fan",
    ),
    TeslaSensorEntityDescription(
        key="fan_status",
        name="Fan Status",
        value_path="climate_state.fan_status",
        icon="mdi:fan",
    ),

    # Drive / Location
    TeslaSensorEntityDescription(
        key="odometer",
        name="Odometer",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        value_path="vehicle_state.odometer",
        conversion="mi_to_km",
        icon="mdi:counter",
    ),
    TeslaSensorEntityDescription(
        key="speed",
        name="Speed",
        device_class=SensorDeviceClass.SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        value_path="drive_state.speed",
        conversion="mph_to_kph",
        icon="mdi:speedometer",
    ),
    TeslaSensorEntityDescription(
        key="latitude",
        name="Latitude",
        value_path="drive_state.latitude",
        icon="mdi:map-marker",
    ),
    TeslaSensorEntityDescription(
        key="longitude",
        name="Longitude",
        value_path="drive_state.longitude",
        icon="mdi:map-marker",
    ),
    TeslaSensorEntityDescription(
        key="heading",
        name="Heading",
        native_unit_of_measurement="°",
        value_path="drive_state.heading",
        icon="mdi:compass",
    ),
    TeslaSensorEntityDescription(
        key="shift_state",
        name="Shift State",
        device_class=SensorDeviceClass.ENUM,
        options=["Driving", "Neutral", "Reverse", "Parking"],
        value_path="drive_state.shift_state",
        icon="mdi:car-shift-pattern",
    ),

    # Vehicle State
    TeslaSensorEntityDescription(
        key="locked",
        name="Locked",
        device_class=SensorDeviceClass.ENUM,
        options=["Locked", "Unlocked"],
        value_path="vehicle_state.locked",
        icon="mdi:lock",
    ),
    TeslaSensorEntityDescription(
        key="sentry_mode",
        name="Sentry Mode",
        device_class=SensorDeviceClass.ENUM,
        options=["On", "Off"],
        value_path="vehicle_state.sentry_mode",
        icon="mdi:shield-car",
    ),
    TeslaSensorEntityDescription(
        key="fd_window",
        name="Front Driver Window",
        device_class=SensorDeviceClass.ENUM,
        options=["Open", "Closed"],
        value_path="vehicle_state.fd_window",
        icon="mdi:car-door",
    ),
    TeslaSensorEntityDescription(
        key="fp_window",
        name="Front Passenger Window",
        device_class=SensorDeviceClass.ENUM,
        options=["Open", "Closed"],
        value_path="vehicle_state.fp_window",
        icon="mdi:car-door",
    ),
    TeslaSensorEntityDescription(
        key="rd_window",
        name="Rear Driver Window",
        device_class=SensorDeviceClass.ENUM,
        options=["Open", "Closed"],
        value_path="vehicle_state.rd_window",
        icon="mdi:car-door",
    ),
    TeslaSensorEntityDescription(
        key="rp_window",
        name="Rear Passenger Window",
        device_class=SensorDeviceClass.ENUM,
        options=["Open", "Closed"],
        value_path="vehicle_state.rp_window",
        icon="mdi:car-door",
    ),
    TeslaSensorEntityDescription(
        key="ft",
        name="Frunk",
        device_class=SensorDeviceClass.ENUM,
        options=["Open", "Closed"],
        value_path="vehicle_state.ft",
        icon="mdi:car-front",
    ),
    TeslaSensorEntityDescription(
        key="trunk",
        name="Rear Trunk",
        value_path="vehicle_state.rt",
        device_class=SensorDeviceClass.ENUM,
        options=["Open", "Closed"],
        icon="mdi:car-back",
    ),
    TeslaSensorEntityDescription(
        key="car_version",
        name="Software Version",
        value_path="vehicle_state.car_version",
        icon="mdi:package-variant",
    ),
    TeslaSensorEntityDescription(
        key="tpms_fl",
        name="Front Left Tire Pressure",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        value_path="vehicle_state.tpms_pressure_fl",
        icon="mdi:car-tire-alert",
    ),
    TeslaSensorEntityDescription(
        key="tpms_fr",
        name="Front Right Tire Pressure",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        value_path="vehicle_state.tpms_pressure_fr",
        icon="mdi:car-tire-alert",
    ),
    TeslaSensorEntityDescription(
        key="tpms_rl",
        name="Rear Left Tire Pressure",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        value_path="vehicle_state.tpms_pressure_rl",
        icon="mdi:car-tire-alert",
    ),
    TeslaSensorEntityDescription(
        key="tpms_rr",
        name="Rear Right Tire Pressure",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        value_path="vehicle_state.tpms_pressure_rr",
        icon="mdi:car-tire-alert",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    coordinator: TeslaVehicleCommandCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities = []
    for vehicle in coordinator.vehicles:
        vin = vehicle["vin"]
        entities.append(TeslaTelemetryStatusSensor(coordinator, vin, vehicle["name"]))
        for description in SENSOR_DESCRIPTIONS:
            entities.append(TeslaSensorEntity(coordinator, vin, vehicle["name"], description))

    async_add_entities(entities)


class TeslaTelemetryStatusSensor(TeslaVehicleCommandEntity, SensorEntity):
    """Diagnostic sensor reporting Fleet Telemetry data flow for a vehicle."""

    _attr_icon = "mdi:transmission-tower"
    _attr_entity_category = "diagnostic"
    _attr_has_entity_name = True
    _attr_should_poll = True
    _attr_translation_key = "telemetry_status"

    def __init__(
        self,
        coordinator: TeslaVehicleCommandCoordinator,
        vin: str,
        vehicle_name: str,
    ) -> None:
        """Initialize the telemetry status sensor."""
        super().__init__(coordinator, vin, vehicle_name)
        self._attr_unique_id = f"{vin}_telemetry_status"

    @property
    def native_value(self) -> str:
        """Return whether telemetry records are arriving for this vehicle."""
        return self.coordinator.get_telemetry_status(self.vin)["state"]

    @property
    def available(self) -> bool:
        """Expose receiver state even if the fallback Fleet API poll fails."""
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the most recent telemetry record diagnostics."""
        metadata = self.coordinator.get_telemetry_status(self.vin)
        last_received = metadata.get("last_received")
        return {
            "last_received": last_received.isoformat() if last_received else None,
            "received_fields": metadata.get("received_fields", []),
            "processed_fields": metadata.get("processed_fields", []),
            "unprocessed_fields": sorted(
                set(metadata.get("received_fields", []))
                - set(metadata.get("processed_fields", []))
            ),
        }


class TeslaSensorEntity(TeslaVehicleCommandEntity, SensorEntity):
    """Sensor entity for Tesla vehicle data."""

    entity_description: TeslaSensorEntityDescription

    def __init__(
        self,
        coordinator: TeslaVehicleCommandCoordinator,
        vin: str,
        vehicle_name: str,
        description: TeslaSensorEntityDescription,
    ) -> None:
        """Initialize the sensor entity."""
        super().__init__(coordinator, vin, vehicle_name)
        self.entity_description = description
        self._attr_unique_id = f"{vin}_{description.key}"

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        vehicle_data = self.coordinator.data.get(self.vin, {})
        response = vehicle_data.get("response", {})

        # Navigate the value path
        value = response
        path = self.entity_description.value_path
        if path:
            for key in path.split("."):
                if isinstance(value, dict):
                    value = value.get(key)
                else:
                    return None

        if value is None:
            if self.entity_description.key == "shift_state":
                return "Parking"
            return None

        if self.entity_description.value_map and value in self.entity_description.value_map:
            return self.entity_description.value_map[value]

        if self.entity_description.key in {
            "fd_window",
            "fp_window",
            "rd_window",
            "rp_window",
            "ft",
            "trunk",
        }:
            return "Closed" if value == 0 else "Open"

        # Apply conversions
        conversion = self.entity_description.conversion
        if conversion == "c_to_f" and isinstance(value, (int, float)):
            return round(value * 9 / 5 + 32, 1)
        elif conversion == "mi_to_km" and isinstance(value, (int, float)):
            return round(value * 1.609344, 1)
        elif conversion == "mph_to_kph" and isinstance(value, (int, float)):
            return round(value * 1.609344, 1)
        elif conversion == "w_to_kw" and isinstance(value, (int, float)):
            return round(value / 1000, 2)
        elif conversion == "wh_to_kwh" and isinstance(value, (int, float)):
            return round(value / 1000, 2)
        elif conversion == "psi_to_bar" and isinstance(value, (int, float)):
            return round(value * 0.0689476, 2)

        # Handle boolean to enum
        if self.entity_description.device_class == SensorDeviceClass.ENUM:
            if isinstance(value, bool):
                if self.entity_description.options == ["Locked", "Unlocked"]:
                    return "Locked" if value else "Unlocked"
                return "On" if value else "Off"
            shift_states = {"D": "Driving", "N": "Neutral", "R": "Reverse", "P": "Parking"}
            return shift_states.get(str(value), str(value).capitalize())

        return value