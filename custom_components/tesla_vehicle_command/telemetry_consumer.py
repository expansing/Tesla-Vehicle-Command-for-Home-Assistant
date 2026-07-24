"""Telemetry consumer for Tesla Fleet Telemetry stream."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp
import zmq
import zmq.asyncio

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DOMAIN, TELEMETRY_ZMQ_ENDPOINT
from .coordinator import TeslaVehicleCommandCoordinator

_LOGGER = logging.getLogger(__name__)

# Signal for telemetry updates
SIGNAL_TELEMETRY_UPDATE = f"{DOMAIN}_telemetry_update"


async def _discover_telemetry_zmq_endpoint(hass: HomeAssistant) -> str:
    """Discover the telemetry addon's ZMQ endpoint via Supervisor API."""
    try:
        session = async_get_clientsession(hass)
        # Query Supervisor API for installed addons
        async with session.get(
            "http://supervisor/addons",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                _LOGGER.warning("Failed to query Supervisor addons API: %s", resp.status)
                return TELEMETRY_ZMQ_ENDPOINT
            
            data = await resp.json()
            addons = data.get("data", {}).get("addons", [])
            
            for addon in addons:
                if addon.get("slug") == TELEMETRY_ADDON_SLUG:
                    # Found the telemetry addon
                    hostname = addon.get("hostname")
                    if hostname:
                        # The addon's hostname in the HA network
                        endpoint = f"tcp://{hostname}:5284"
                        _LOGGER.info("Discovered telemetry addon ZMQ endpoint: %s", endpoint)
                        return endpoint
                    
                    # Fallback: try to get IP from network info
                    network = addon.get("network", {})
                    ip = network.get("ip")
                    if ip:
                        endpoint = f"tcp://{ip}:5284"
                        _LOGGER.info("Discovered telemetry addon ZMQ endpoint via IP: %s", endpoint)
                        return endpoint
            
            _LOGGER.warning("Telemetry addon '%s' not found in Supervisor API", TELEMETRY_ADDON_SLUG)
            return TELEMETRY_ZMQ_ENDPOINT
            
    except Exception as err:
        _LOGGER.warning("Failed to discover telemetry addon endpoint: %s", err)
        return TELEMETRY_ZMQ_ENDPOINT


class TelemetryConsumer:
    """Consumes Fleet Telemetry stream from ZMQ and updates coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: TeslaVehicleCommandCoordinator,
        zmq_endpoint: str | None = None,
    ) -> None:
        """Initialize the telemetry consumer."""
        self.hass = hass
        self.coordinator = coordinator
        self._zmq_endpoint = zmq_endpoint
        self._context: zmq.asyncio.Context | None = None
        self._socket: zmq.asyncio.Socket | None = None
        self._task: asyncio.Task | None = None
        self._running = False

    async def async_start(self) -> None:
        """Start consuming telemetry data."""
        if self._running:
            return

        # Discover the ZMQ endpoint if not provided
        if self._zmq_endpoint is None:
            self._zmq_endpoint = await _discover_telemetry_zmq_endpoint(self.hass)
        
        self._context = zmq.asyncio.Context()
        self._socket = self._context.socket(zmq.SUB)
        self._socket.setsockopt(zmq.SUBSCRIBE, b"")
        _LOGGER.info("Connecting to Fleet Telemetry ZMQ at %s", self._zmq_endpoint)
        self._socket.connect(self._zmq_endpoint)

        self._running = True
        self._task = asyncio.create_task(self._consume_loop())
        _LOGGER.info("Started Fleet Telemetry consumer on %s", self._zmq_endpoint)

    async def async_stop(self) -> None:
        """Stop consuming telemetry data."""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._socket:
            self._socket.close()
        if self._context:
            self._context.term()

        _LOGGER.info("Stopped Fleet Telemetry consumer")

    async def _consume_loop(self) -> None:
        """Main loop to consume telemetry messages."""
        _LOGGER.debug("Telemetry consume loop started")
        while self._running:
            try:
                # Receive multipart message: [topic, payload]
                parts = await self._socket.recv_multipart()
                _LOGGER.debug("Received telemetry message: topic=%s, parts=%d", parts[0].decode("utf-8", errors="ignore") if parts else "none", len(parts))
                if len(parts) >= 2:
                    topic = parts[0].decode("utf-8", errors="ignore")
                    payload = parts[1]
                    await self._process_message(topic, payload)
            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.error("Error in telemetry consume loop: %s", err)
                await asyncio.sleep(1)

    async def _process_message(self, topic: str, payload: bytes) -> None:
        """Process a single telemetry message."""
        _LOGGER.debug("Processing telemetry message: topic=%s, payload_size=%d", topic, len(payload))
        try:
            # The payload is JSON from the fleet-telemetry receiver
            data = json.loads(payload.decode("utf-8"))
            
            # Extract VIN from the message
            vin = data.get("vin")
            if not vin:
                _LOGGER.debug("Telemetry message missing VIN: %s", topic)
                return

            # Check if this vehicle is managed by us
            vehicle_config = self.coordinator.get_vehicle_config(vin)
            if not vehicle_config:
                _LOGGER.debug("Telemetry for unmanaged vehicle: %s", vin)
                return

            _LOGGER.debug("Processing telemetry for vehicle %s, topic: %s", vin, topic)
            # Process based on topic/type
            await self._update_coordinator_data(vin, topic, data)

        except json.JSONDecodeError as err:
            _LOGGER.debug("Failed to decode telemetry payload: %s", err)
        except Exception as err:
            _LOGGER.error("Error processing telemetry message: %s", err)

    async def _update_coordinator_data(
        self, vin: str, topic: str, data: dict[str, Any]
    ) -> None:
        """Update coordinator data with telemetry."""
        # Get current vehicle data
        current_data = self.coordinator.data.get(vin, {})
        response = current_data.get("response", {})

        # Mark telemetry as active for this vehicle
        self.coordinator.set_telemetry_active(vin, True)

        # Handle different topic formats:
        # - tesla_telemetry_V (repo addon format)
        # - V (local addon format)
        # - connectivity, alerts, errors
        actual_topic = topic
        if topic.startswith("tesla_telemetry_"):
            actual_topic = topic[len("tesla_telemetry_"):]
            _LOGGER.debug("Normalized topic from %s to %s", topic, actual_topic)

        # Update based on topic
        if actual_topic == "V":
            # Vehicle telemetry data - contains the actual signal values
            _LOGGER.info("Received vehicle telemetry data for %s", vin)
            await self._process_vehicle_signals(vin, response, data)
        elif actual_topic == "connectivity":
            # Connectivity events - vehicle online/offline
            _LOGGER.info("Received connectivity event for %s: %s", vin, data.get("status", "unknown"))
            await self._process_connectivity(vin, response, data)
        elif actual_topic == "alerts":
            # Alerts
            _LOGGER.warning("Telemetry alert for %s: %s", vin, data)
        elif actual_topic == "errors":
            # Errors
            _LOGGER.warning("Telemetry error for %s: %s", vin, data)
        else:
            _LOGGER.debug("Unknown telemetry topic: %s (original: %s)", actual_topic, topic)

        # Update coordinator data and trigger refresh
        self.coordinator.data[vin] = {"response": response}
        async_dispatcher_send(self.hass, SIGNAL_TELEMETRY_UPDATE, vin)

    async def _process_vehicle_signals(
        self, vin: str, response: dict[str, Any], data: dict[str, Any]
    ) -> None:
        """Process vehicle signal data from telemetry."""
        # The telemetry data contains signal values
        # Format: {"vin": "...", "timestamp": ..., "signals": {...}}
        signals = data.get("signals", {})
        
        _LOGGER.info("Processing %d signals for vehicle %s: %s", len(signals), vin, list(signals.keys()))
        
        # Ensure all state containers exist
        response.setdefault("charge_state", {})
        response.setdefault("climate_state", {})
        response.setdefault("vehicle_state", {})
        response.setdefault("drive_state", {})

        # Map telemetry signals to vehicle data structure
        signal_mapping = {
            # Battery/Charging
            "Soc": ("charge_state", "battery_level"),
            "BatteryLevel": ("charge_state", "battery_level"),
            "EstBatteryRange": ("charge_state", "battery_range"),
            "IdealBatteryRange": ("charge_state", "ideal_battery_range"),
            "DetailedChargeState": ("charge_state", "charging_state"),
            "ChargeLimitSoc": ("charge_state", "charge_limit_soc"),
            "TimeToFullCharge": ("charge_state", "time_to_full_charge"),
            "ACChargingPower": ("charge_state", "charger_power"),
            "DCChargingPower": ("charge_state", "charger_power"),
            "ChargePortDoorOpen": ("charge_state", "charge_port_door_open"),
            
            # Climate
            "InsideTemp": ("climate_state", "inside_temp"),
            "OutsideTemp": ("climate_state", "outside_temp"),
            "HvacPower": ("climate_state", "is_climate_on"),
            
            # Vehicle State
            "Locked": ("vehicle_state", "locked"),
            "SentryMode": ("vehicle_state", "sentry_mode"),
            
            # Drive State
            "Gear": ("drive_state", "shift_state"),
            "VehicleSpeed": ("drive_state", "speed"),
            "Odometer": ("vehicle_state", "odometer"),
            
            # Version
            "Version": ("vehicle_state", "car_version"),
        }

        for signal_name, (state_category, state_key) in signal_mapping.items():
            if signal_name in signals:
                value = signals[signal_name]
                # Convert value if needed
                converted_value = self._convert_signal_value(signal_name, value)
                response[state_category][state_key] = converted_value
                _LOGGER.debug("Mapped signal %s -> %s.%s = %s", signal_name, state_category, state_key, converted_value)

        _LOGGER.debug("Updated telemetry data for %s: %d signals", vin, len(signals))

    async def _process_connectivity(
        self, vin: str, response: dict[str, Any], data: dict[str, Any]
    ) -> None:
        """Process connectivity events."""
        # Connectivity events indicate vehicle online/offline/sleeping
        status = data.get("status", "unknown")
        response.setdefault("vehicle_state", {})
        response["vehicle_state"]["connectivity_status"] = status
        
        # If vehicle just came online, we might want to trigger a full refresh
        if status == "online":
            _LOGGER.info("Vehicle %s came online via telemetry", vin)

    def _convert_signal_value(self, signal_name: str, value: Any) -> Any:
        """Convert telemetry signal value to HA-friendly format."""
        # Temperature conversions (from tenths of Celsius to Celsius)
        if signal_name in ("InsideTemp", "OutsideTemp"):
            if isinstance(value, (int, float)):
                return round(value / 10.0, 1)
        
        # Power conversions (from watts to kW)
        if signal_name in ("ACChargingPower", "DCChargingPower"):
            if isinstance(value, (int, float)):
                return round(value / 1000.0, 2)
        
        # Speed conversion (from m/s to km/h)
        if signal_name == "VehicleSpeed":
            if isinstance(value, (int, float)):
                return round(value * 3.6, 1)
        
        # Odometer conversion (from meters to km)
        if signal_name == "Odometer":
            if isinstance(value, (int, float)):
                return round(value / 1000.0, 1)
        
        # Range conversions (from meters to km)
        if signal_name in ("EstBatteryRange", "IdealBatteryRange"):
            if isinstance(value, (int, float)):
                return round(value / 1000.0, 1)
        
        # Battery percentage (from 0-1000 to 0-100)
        if signal_name in ("Soc", "BatteryLevel", "ChargeLimitSoc"):
            if isinstance(value, (int, float)):
                return round(value / 10.0, 1)
        
        # Boolean conversions
        if signal_name in ("Locked", "SentryMode", "ChargePortDoorOpen", "HvacPower"):
            if isinstance(value, (int, float)):
                return bool(value)
        
        # Gear/shift state mapping
        if signal_name == "Gear":
            gear_map = {
                "D": "Driving",
                "N": "Neutral",
                "R": "Reverse",
                "P": "Parking",
            }
            return gear_map.get(str(value), str(value))
        
        # Charging state mapping
        if signal_name == "DetailedChargeState":
            charge_map = {
                "Charging": "Charging",
                "Complete": "Complete",
                "Disconnected": "Disconnected",
                "Stopped": "Stopped",
                "NoPower": "NoPower",
            }
            return charge_map.get(str(value), str(value))
        
        return value


async def async_setup_telemetry_consumer(
    hass: HomeAssistant,
    coordinator: TeslaVehicleCommandCoordinator,
) -> TelemetryConsumer:
    """Set up and start the telemetry consumer."""
    consumer = TelemetryConsumer(hass, coordinator)
    await consumer.async_start()
    return consumer