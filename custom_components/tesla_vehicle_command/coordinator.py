"""Data coordinator for Tesla Vehicle Command."""

from __future__ import annotations

import logging
import ssl
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_COMMAND,
    API_FLEET_TELEMETRY_CONFIG,
    API_WAKE_UP,
    COMMAND_BODIES,
    COMMANDS,
    CONF_TELEMETRY_HOSTNAME,
    CONF_TELEMETRY_PORT,
    DOMAIN,
    PROXY_HOST,
    PROXY_PORT,
)
from .proxy_manager import ProxyManager

_LOGGER = logging.getLogger(__name__)

_FLEET_TELEMETRY_FIELDS = {
    "Soc": {"interval_seconds": 60},
    "BatteryLevel": {"interval_seconds": 60},
    "RatedRange": {"interval_seconds": 60},
    "EstBatteryRange": {"interval_seconds": 60},
    "IdealBatteryRange": {"interval_seconds": 60},
    "DetailedChargeState": {"interval_seconds": 60},
    "ChargeLimitSoc": {"interval_seconds": 300},
    "TimeToFullCharge": {"interval_seconds": 60},
    "ChargerVoltage": {"interval_seconds": 60},
    "ChargeAmps": {"interval_seconds": 60},
    "ACChargingPower": {"interval_seconds": 60},
    "DCChargingPower": {"interval_seconds": 60},
    "ACChargingEnergyIn": {"interval_seconds": 60},
    "DCChargingEnergyIn": {"interval_seconds": 60},
    "ChargePortDoorOpen": {"interval_seconds": 60},
    "InsideTemp": {"interval_seconds": 300},
    "OutsideTemp": {"interval_seconds": 300},
    "HvacLeftTemperatureRequest": {"interval_seconds": 300},
    "HvacRightTemperatureRequest": {"interval_seconds": 300},
    "HvacFanStatus": {"interval_seconds": 60},
    "HvacPower": {"interval_seconds": 60},
    "PreconditioningEnabled": {"interval_seconds": 60},
    "ClimateKeeperMode": {"interval_seconds": 300},
    "DefrostMode": {"interval_seconds": 60},
    "SeatHeaterLeft": {"interval_seconds": 60},
    "SeatHeaterRight": {"interval_seconds": 60},
    "SeatHeaterRearLeft": {"interval_seconds": 60},
    "SeatHeaterRearRight": {"interval_seconds": 60},
    "SeatHeaterRearCenter": {"interval_seconds": 60},
    "HvacSteeringWheelHeatLevel": {"interval_seconds": 60},
    "Locked": {"interval_seconds": 60},
    "SentryMode": {"interval_seconds": 300},
    "DoorState": {"interval_seconds": 60},
    "DriverSeatOccupied": {"interval_seconds": 60},
    "Gear": {"interval_seconds": 2},
    "VehicleSpeed": {"interval_seconds": 2},
    "GpsHeading": {"interval_seconds": 2},
    "Location": {"interval_seconds": 2},
    "Odometer": {"interval_seconds": 300},
    "Version": {"interval_seconds": 3600},
    "FdWindow": {"interval_seconds": 60},
    "FpWindow": {"interval_seconds": 60},
    "RdWindow": {"interval_seconds": 60},
    "RpWindow": {"interval_seconds": 60},
    "TpmsPressureFl": {"interval_seconds": 300},
    "TpmsPressureFr": {"interval_seconds": 300},
    "TpmsPressureRl": {"interval_seconds": 300},
    "TpmsPressureRr": {"interval_seconds": 300},
}

_TELEMETRY_STORE_VERSION = 2


class TeslaVehicleCommandCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching Tesla vehicle data."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        proxy_manager: ProxyManager,
    ) -> None:
        """Initialize."""
        self.entry = entry
        self.proxy_manager = proxy_manager
        self._vehicles = entry.data.get("vehicles", [])
        self._access_token: str | None = None
        self._token_expires_at: float = 0
        self._telemetry_store = Store[dict[str, Any]](
            hass,
            _TELEMETRY_STORE_VERSION,
            f"{DOMAIN}.{entry.entry_id}.telemetry",
        )
        self._telemetry_receiver_available = False
        self._telemetry_metadata: dict[str, dict[str, Any]] = {}
        self._telemetry_raw_signals: dict[str, dict[str, Any]] = {}

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,
        )

    @property
    def vehicles(self) -> list[dict[str, Any]]:
        """Return configured vehicles."""
        return self._vehicles

    @property
    def access_token(self) -> str | None:
        """Return current access token."""
        return self._access_token

    def set_telemetry_receiver_available(self, available: bool) -> None:
        """Set whether the local Fleet Telemetry receiver is reachable."""
        self._telemetry_receiver_available = available

    def record_telemetry_update(
        self,
        vin: str,
        received_fields: set[str],
        processed_fields: set[str],
    ) -> None:
        """Record a successfully processed telemetry message for a vehicle."""
        self._telemetry_metadata[vin] = {
            "last_received": datetime.now().astimezone(),
            "received_fields": sorted(received_fields),
            "processed_fields": sorted(processed_fields),
        }

    def get_telemetry_status(self, vin: str) -> dict[str, Any]:
        """Return telemetry health and diagnostic metadata for a vehicle."""
        metadata = self._telemetry_metadata.get(vin, {})
        last_received = metadata.get("last_received")
        if last_received and datetime.now().astimezone() - last_received <= timedelta(
            minutes=15
        ):
            state = "receiving"
        elif last_received:
            state = "stale"
        elif self._telemetry_receiver_available:
            state = "waiting"
        else:
            state = "unavailable"

        return {"state": state, **metadata}

    @staticmethod
    def _empty_response() -> dict[str, dict[str, Any]]:
        """Return the Fleet API-shaped state used before telemetry arrives."""
        return {
            "charge_state": {},
            "climate_state": {},
            "drive_state": {},
            "vehicle_state": {},
        }

    def _empty_telemetry_data(self) -> dict[str, dict[str, Any]]:
        """Return empty telemetry-backed data for configured vehicles."""
        return {
            vehicle["vin"]: {"response": self._empty_response()}
            for vehicle in self._vehicles
        }

    async def async_load_telemetry_cache(self) -> None:
        """Restore the last telemetry state without reading vehicle data from Tesla."""
        stored_cache = await self._telemetry_store.async_load()
        data = self._empty_telemetry_data()
        stored_data = (
            stored_cache.get("vehicles", {})
            if isinstance(stored_cache, dict) and "vehicles" in stored_cache
            else stored_cache
        )
        if isinstance(stored_data, dict):
            for vin in data:
                cached_vehicle = stored_data.get(vin)
                cached_response = (
                    cached_vehicle.get("response")
                    if isinstance(cached_vehicle, dict)
                    else None
                )
                if isinstance(cached_response, dict):
                    data[vin] = {"response": cached_response}

        if not isinstance(stored_cache, dict):
            self.async_set_updated_data(data)
            return

        for vin, metadata in stored_cache.get("metadata", {}).items():
            if vin not in data or not isinstance(metadata, dict):
                continue
            last_received = metadata.get("last_received")
            if isinstance(last_received, str):
                try:
                    last_received = datetime.fromisoformat(last_received)
                except ValueError:
                    continue
            if isinstance(last_received, datetime):
                self._telemetry_metadata[vin] = {
                    "last_received": last_received,
                    "received_fields": metadata.get("received_fields", []),
                    "processed_fields": metadata.get("processed_fields", []),
                }

        raw_signals = stored_cache.get("raw_signals", {})
        if isinstance(raw_signals, dict):
            self._telemetry_raw_signals = {
                vin: signals
                for vin, signals in raw_signals.items()
                if vin in data and isinstance(signals, dict)
            }
        self.async_set_updated_data(data)

    def get_telemetry_raw_signals(self, vin: str) -> dict[str, Any]:
        """Return persisted raw signals used to reassemble delta records."""
        return dict(self._telemetry_raw_signals.get(vin, {}))

    def _telemetry_store_payload(self) -> dict[str, Any]:
        """Serialize telemetry state and diagnostics for local storage."""
        metadata = {
            vin: {
                **details,
                "last_received": details["last_received"].isoformat(),
            }
            for vin, details in self._telemetry_metadata.items()
            if isinstance(details.get("last_received"), datetime)
        }
        return {
            "vehicles": self.data if isinstance(self.data, dict) else {},
            "metadata": metadata,
            "raw_signals": self._telemetry_raw_signals,
        }

    def set_telemetry_data(
        self,
        vin: str,
        response: dict[str, Any],
        received_fields: set[str] | None = None,
        processed_fields: set[str] | None = None,
        raw_signals: dict[str, Any] | None = None,
    ) -> None:
        """Publish and persist state sourced exclusively from telemetry."""
        if received_fields is not None and processed_fields is not None:
            self.record_telemetry_update(vin, received_fields, processed_fields)
        if raw_signals is not None:
            self._telemetry_raw_signals[vin] = dict(raw_signals)

        updated_data = dict(self.data or self._empty_telemetry_data())
        updated_data[vin] = {"response": response}
        self.async_set_updated_data(updated_data)
        self._telemetry_store.async_delay_save(
            self._telemetry_store_payload, 30
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Return cached telemetry state without polling Tesla vehicle data."""
        return self.data or self._empty_telemetry_data()

    async def _ensure_valid_token(self) -> None:
        """Ensure we have a valid access token."""
        import time

        if self._access_token and time.time() < self._token_expires_at - 60:
            return

        # Token expired or not set, refresh from config entry
        tokens = self.entry.data.get("tokens", {})
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise UpdateFailed("No refresh token available")

        # Refresh token
        await self._refresh_access_token(refresh_token)

    async def _refresh_access_token(self, refresh_token: str) -> None:
        """Refresh the access token."""
        import time

        client_id = self.entry.data.get("client_id")
        client_secret = self.entry.data.get("client_secret")

        if not client_id or not client_secret:
            raise UpdateFailed("Missing OAuth credentials")

        session = async_get_clientsession(self.hass)
        data = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        }

        async with session.post(
            "https://auth.tesla.com/oauth2/v3/token",
            data=data,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise UpdateFailed(f"Token refresh failed: {resp.status} - {text}")

            token_data = await resp.json()

        self._access_token = token_data["access_token"]
        expires_in = token_data.get("expires_in", 28800)
        self._token_expires_at = time.time() + expires_in

        # Update stored tokens
        tokens = self.entry.data.get("tokens", {})
        new_tokens = {
            **tokens,
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token", refresh_token),
            "expires_at": int(self._token_expires_at),
        }

        # Update config entry
        new_data = {**self.entry.data, "tokens": new_tokens}
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)

        _LOGGER.debug("Refreshed access token")

    async def _get_ssl_context(self) -> aiohttp.ClientSSLContext:
        """Get SSL context for proxy communication."""
        ca_path = self.proxy_manager.cert_path
        if not ca_path or not ca_path.exists():
            # Fallback: disable verification (not recommended for production)
            return False

        def _create_ssl_context() -> ssl.SSLContext:
            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.load_verify_locations(str(ca_path))
            return ssl_context

        return await self.hass.async_add_executor_job(_create_ssl_context)

    async def async_send_command(
        self,
        vin: str,
        command: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a command to the vehicle."""
        if not self.proxy_manager.is_running:
            raise RuntimeError("Proxy not running")

        await self._ensure_valid_token()

        session = async_get_clientsession(self.hass)
        ssl_context = await self._get_ssl_context()

        cmd = COMMANDS.get(command, command)
        url = f"https://{PROXY_HOST}:{PROXY_PORT}{API_COMMAND.format(vin=vin, command=cmd)}"
        headers = {"Authorization": f"Bearer {self._access_token}", "Content-Type": "application/json"}

        # Use predefined body or provided body
        if body is None:
            body = COMMAND_BODIES.get(command, {})

        async with session.post(url, headers=headers, json=body, ssl=ssl_context, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status == 401:
                self._token_expires_at = 0
                await self._ensure_valid_token()
                headers["Authorization"] = f"Bearer {self._access_token}"
                async with session.post(url, headers=headers, json=body, ssl=ssl_context, timeout=aiohttp.ClientTimeout(total=30)) as retry_resp:
                    if retry_resp.status != 200:
                        text = await retry_resp.text()
                        raise RuntimeError(f"Command failed: {retry_resp.status} - {text}")
                    return await retry_resp.json()

            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Command failed: {resp.status} - {text}")

            return await resp.json()

    async def async_wake_up(self, vin: str) -> dict[str, Any]:
        """Wake up the vehicle."""
        if not self.proxy_manager.is_running:
            raise RuntimeError("Proxy not running")

        await self._ensure_valid_token()

        session = async_get_clientsession(self.hass)
        ssl_context = await self._get_ssl_context()

        url = f"https://{PROXY_HOST}:{PROXY_PORT}{API_WAKE_UP.format(vin=vin)}"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

        async with session.post(
            url,
            headers=headers,
            json={},
            ssl=ssl_context,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Wake up failed: {resp.status} - {text}")

            return await resp.json()

    async def async_configure_fleet_telemetry(self, vin: str) -> dict[str, Any]:
        """Register a Fleet Telemetry destination through the command proxy."""
        if not self.proxy_manager.is_running:
            raise RuntimeError("Proxy not running")

        hostname = self.entry.options.get(CONF_TELEMETRY_HOSTNAME, "").strip()
        port = self.entry.options.get(CONF_TELEMETRY_PORT)
        ca_path = self.proxy_manager.telemetry_ca_path
        if not hostname or not port or not ca_path or not ca_path.is_file():
            raise RuntimeError(
                "Configure a telemetry hostname and restart the integration first"
            )

        await self._ensure_valid_token()
        telemetry_ca = await self.hass.async_add_executor_job(ca_path.read_text)
        session = async_get_clientsession(self.hass)
        ssl_context = await self._get_ssl_context()
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        body = {
            "vins": [vin],
            "config": {
                "hostname": hostname,
                "port": int(port),
                "ca": telemetry_ca,
                "fields": _FLEET_TELEMETRY_FIELDS,
            },
        }
        url = f"https://{PROXY_HOST}:{PROXY_PORT}{API_FLEET_TELEMETRY_CONFIG}"
        async with session.post(
            url,
            headers=headers,
            json=body,
            ssl=ssl_context,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            if response.status != 200:
                text = await response.text()
                raise RuntimeError(
                    f"Fleet Telemetry configuration failed: {response.status} - {text}"
                )
            return await response.json()

    def get_vehicle_config(self, vin: str) -> dict[str, Any] | None:
        """Get vehicle configuration."""
        for vehicle in self._vehicles:
            if vehicle["vin"] == vin:
                return vehicle
        return None
