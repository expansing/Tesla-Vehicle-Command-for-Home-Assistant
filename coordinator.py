"""Data coordinator for Tesla Vehicle Command."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_COMMAND,
    API_VEHICLE_DATA,
    API_VEHICLES,
    API_WAKE_UP,
    COMMAND_BODIES,
    COMMANDS,
    DOMAIN,
    PROXY_HOST,
    PROXY_PORT,
    UPDATE_INTERVAL_AWAKE,
    UPDATE_INTERVAL_CHARGING,
    UPDATE_INTERVAL_VEHICLE_DATA,
)
from .proxy_manager import ProxyManager

_LOGGER = logging.getLogger(__name__)


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

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_VEHICLE_DATA),
        )

    @property
    def vehicles(self) -> list[dict[str, Any]]:
        """Return configured vehicles."""
        return self._vehicles

    @property
    def access_token(self) -> str | None:
        """Return current access token."""
        return self._access_token

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from all vehicles."""
        if not self.proxy_manager.is_running:
            raise UpdateFailed("Proxy not running")

        # Ensure we have a valid token
        await self._ensure_valid_token()

        data = {}
        for vehicle in self._vehicles:
            vin = vehicle["vin"]
            try:
                vehicle_data = await self._fetch_vehicle_data(vin)
                data[vin] = vehicle_data
            except Exception as err:
                _LOGGER.error("Error fetching data for %s: %s", vin, err)
                data[vin] = {"error": str(err)}

        return data

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

    async def _fetch_vehicle_data(self, vin: str) -> dict[str, Any]:
        """Fetch vehicle data from proxy."""
        session = async_get_clientsession(self.hass)
        ssl_context = self._get_ssl_context()

        url = f"https://{PROXY_HOST}:{PROXY_PORT}{API_VEHICLE_DATA.format(vin=vin)}"
        headers = {"Authorization": f"Bearer {self._access_token}"}

        async with session.get(url, headers=headers, ssl=ssl_context, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status == 401:
                # Token might be expired, force refresh
                self._token_expires_at = 0
                await self._ensure_valid_token()
                headers["Authorization"] = f"Bearer {self._access_token}"
                async with session.get(url, headers=headers, ssl=ssl_context, timeout=aiohttp.ClientTimeout(total=30)) as retry_resp:
                    if retry_resp.status != 200:
                        text = await retry_resp.text()
                        raise UpdateFailed(f"Vehicle data fetch failed: {retry_resp.status} - {text}")
                    return await retry_resp.json()

            if resp.status != 200:
                text = await resp.text()
                raise UpdateFailed(f"Vehicle data fetch failed: {resp.status} - {text}")

            return await resp.json()

    def _get_ssl_context(self) -> aiohttp.ClientSSLContext:
        """Get SSL context for proxy communication."""
        import ssl

        ca_path = self.proxy_manager.cert_path
        if not ca_path or not ca_path.exists():
            # Fallback: disable verification (not recommended for production)
            return False

        ssl_context = ssl.create_default_context()
        ssl_context.load_verify_locations(str(ca_path))
        return ssl_context

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
        ssl_context = self._get_ssl_context()

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
        ssl_context = self._get_ssl_context()

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

    def get_vehicle_config(self, vin: str) -> dict[str, Any] | None:
        """Get vehicle configuration."""
        for vehicle in self._vehicles:
            if vehicle["vin"] == vin:
                return vehicle
        return None

    def get_update_interval(self, vehicle_data: dict[str, Any]) -> int:
        """Determine update interval based on vehicle state."""
        if not vehicle_data or "response" not in vehicle_data:
            return UPDATE_INTERVAL_VEHICLE_DATA

        response = vehicle_data["response"]
        charge_state = response.get("charge_state", {})
        drive_state = response.get("drive_state", {})

        # Charging - frequent updates
        if charge_state.get("charging_state") == "Charging":
            return UPDATE_INTERVAL_CHARGING

        # Driving - frequent updates
        if drive_state.get("shift_state") not in (None, "P"):
            return UPDATE_INTERVAL_AWAKE

        # Awake but not charging/driving
        if response.get("state") == "online":
            return UPDATE_INTERVAL_AWAKE

        # Asleep - normal interval
        return UPDATE_INTERVAL_VEHICLE_DATA
