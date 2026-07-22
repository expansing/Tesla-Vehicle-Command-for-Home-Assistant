"""Config flow for Tesla Vehicle Command integration."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import (
    _encode_jwt,
    async_get_redirect_uri,
)

from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_VEHICLES,
    CONF_VIN,
    CONF_NAME,
    CONF_PRIVATE_KEY_PATH,
    DOMAIN,
    OAUTH2_AUTHORIZE,
    OAUTH2_SCOPES,
    OAUTH2_TOKEN,
)

_LOGGER = logging.getLogger(__name__)

# Step 1: User provides OAuth credentials
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CLIENT_ID): str,
        vol.Required(CONF_CLIENT_SECRET): str,
    }
)

# Step 3: Vehicle selection
STEP_VEHICLE_SCHEMA = vol.Schema(
    {
        vol.Required("vehicles"): vol.All(
            list,
            vol.Length(min=1),
        ),
    }
)

# Step 4: Private key - generate or import
STEP_KEY_SCHEMA = vol.Schema(
    {
        vol.Required("key_action"): vol.In(["generate", "import"]),
        vol.Optional("private_key"): str,
    }
)


class TeslaVehicleCommandConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tesla Vehicle Command."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._client_id: str | None = None
        self._client_secret: str | None = None
        self._redirect_uri: str | None = None
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._vehicles: list[dict[str, Any]] = []
        self._selected_vehicles: list[str] = []
        self._auth_url: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - OAuth credentials."""
        errors = {}

        if user_input is not None:
            self._client_id = user_input[CONF_CLIENT_ID]
            self._client_secret = user_input[CONF_CLIENT_SECRET]

            # Validate credentials by trying to get auth URL
            try:
                self._auth_url = await self._generate_auth_url()
                return await self.async_step_auth()
            except Exception as err:
                _LOGGER.error("Failed to generate auth URL: %s", err)
                errors["base"] = "auth_failed"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "docs_url": "https://developer.tesla.com/docs/fleet-api/authentication/third-party-tokens"
            },
        )

    async def async_step_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle Tesla's OAuth callback."""
        if user_input is not None:
            if "error" in user_input:
                return self.async_abort(reason="authorize_rejected")
            try:
                await self._exchange_code_for_tokens(user_input["code"])
            except Exception as err:
                _LOGGER.error("Token exchange failed: %s", err)
                return self.async_abort(reason="token_exchange_failed")
            return self.async_external_step_done(next_step_id="vehicles")

        return self.async_external_step(
            step_id="auth",
            url=self._auth_url or "",
        )

    async def _generate_auth_url(self) -> str:
        """Generate Tesla OAuth authorization URL."""
        self._redirect_uri = async_get_redirect_uri(self.hass)
        state = _encode_jwt(
            self.hass,
            {"flow_id": self.flow_id, "redirect_uri": self._redirect_uri},
        )

        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": " ".join(OAUTH2_SCOPES),
            "state": state,
        }

        return f"{OAUTH2_AUTHORIZE}?{urlencode(params)}"

    async def async_step_vehicles(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select vehicles to add."""
        errors = {}

        if user_input and "vehicles" in user_input:
            self._selected_vehicles = user_input["vehicles"]
            return await self.async_step_key()

        # Fetch vehicle list if not already done
        if not self._vehicles:
            try:
                self._vehicles = await self._fetch_vehicles()
            except Exception as err:
                _LOGGER.error("Failed to fetch vehicles: %s", err)
                errors["base"] = "fetch_vehicles_failed"
                return self.async_show_form(
                    step_id="vehicles",
                    data_schema=vol.Schema({}),
                    errors=errors,
                )

        if not self._vehicles:
            errors["base"] = "no_vehicles"
            return self.async_show_form(
                step_id="vehicles",
                data_schema=vol.Schema({}),
                errors=errors,
            )

        # Build vehicle selection schema
        vehicle_options = {
            v["vin"]: f"{v.get('display_name', v['vin'])} ({v['vin']})"
            for v in self._vehicles
        }

        schema = vol.Schema(
            {
                vol.Required("vehicles"): vol.All(
                    vol.MultiSelect(vehicle_options),
                    vol.Length(min=1),
                )
            }
        )

        return self.async_show_form(
            step_id="vehicles",
            data_schema=schema,
            errors=errors,
        )

    async def _fetch_vehicles(self) -> list[dict[str, Any]]:
        """Fetch vehicle list from Tesla Fleet API."""
        if not self._access_token:
            raise RuntimeError("No access token")

        session = async_get_clientsession(self.hass)
        headers = {"Authorization": f"Bearer {self._access_token}"}

        async with session.get(
            "https://fleet-api.prd.na.vn.cloud.tesla.com/api/1/vehicles",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Failed to fetch vehicles: {resp.status} - {text}")

            data = await resp.json()
            return data.get("response", [])

    async def async_step_key(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle private key generation or import."""
        errors = {}

        if user_input is not None:
            action = user_input["key_action"]

            if action == "generate":
                # Generate new key pair
                private_key_path = await self._generate_key_pair()
            elif action == "import":
                private_key = user_input.get("private_key", "").strip()
                if not private_key:
                    errors["private_key"] = "required"
                    return self.async_show_form(
                        step_id="key",
                        data_schema=STEP_KEY_SCHEMA,
                        errors=errors,
                    )
                private_key_path = await self._import_private_key(private_key)
            else:
                errors["base"] = "invalid_action"
                return self.async_show_form(
                    step_id="key",
                    data_schema=STEP_KEY_SCHEMA,
                    errors=errors,
                )

            # Create config entry
            return await self._create_entry(private_key_path)

        return self.async_show_form(
            step_id="key",
            data_schema=STEP_KEY_SCHEMA,
            errors=errors,
            description_placeholders={
                "enroll_url": "https://www.tesla.com/teslaaccount/keys"
            },
        )

    async def _generate_key_pair(self) -> str:
        """Generate a new ECDH key pair for vehicle command authentication."""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        # Generate private key
        private_key = ec.generate_private_key(ec.SECP256R1())

        # Serialize to PEM
        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        # Save to config directory
        key_dir = self.hass.config.path(DOMAIN, "keys")
        import os
        os.makedirs(key_dir, exist_ok=True)

        # Use first selected VIN for filename
        vin = self._selected_vehicles[0]
        key_path = os.path.join(key_dir, f"{vin}.pem")

        with open(key_path, "wb") as f:
            f.write(pem)

        # Set restrictive permissions
        os.chmod(key_path, 0o600)

        _LOGGER.info("Generated private key at %s", key_path)
        return key_path

    async def _import_private_key(self, private_key_pem: str) -> str:
        """Import an existing private key."""
        import os

        # Validate it's a valid PEM
        from cryptography.hazmat.primitives import serialization

        try:
            serialization.load_pem_private_key(
                private_key_pem.encode(),
                password=None,
            )
        except Exception as err:
            raise ValueError(f"Invalid private key: {err}")

        # Save to config directory
        key_dir = self.hass.config.path(DOMAIN, "keys")
        os.makedirs(key_dir, exist_ok=True)

        vin = self._selected_vehicles[0]
        key_path = os.path.join(key_dir, f"{vin}.pem")

        with open(key_path, "w") as f:
            f.write(private_key_pem)

        os.chmod(key_path, 0o600)

        _LOGGER.info("Imported private key to %s", key_path)
        return key_path

    async def _create_entry(self, private_key_path: str) -> FlowResult:
        """Create the config entry."""
        vehicles_data = []
        for vin in self._selected_vehicles:
            vehicle = next((v for v in self._vehicles if v["vin"] == vin), None)
            if vehicle:
                vehicles_data.append(
                    {
                        CONF_VIN: vin,
                        CONF_NAME: vehicle.get("display_name", vin),
                        CONF_PRIVATE_KEY_PATH: private_key_path,
                    }
                )

        data = {
            CONF_CLIENT_ID: self._client_id,
            CONF_CLIENT_SECRET: self._client_secret,
            CONF_VEHICLES: vehicles_data,
            "tokens": {
                "access_token": self._access_token,
                "refresh_token": self._refresh_token,
                "expires_at": 0,  # Will be updated on first refresh
            },
        }

        return self.async_create_entry(
            title="Tesla Vehicle Command",
            data=data,
        )

    async def _exchange_code_for_tokens(self, code: str) -> None:
        """Exchange authorization code for access/refresh tokens."""
        if not self._redirect_uri:
            raise RuntimeError("OAuth redirect URI is not initialized")

        session = async_get_clientsession(self.hass)
        token_data = {
            "grant_type": "authorization_code",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "code": code,
            "redirect_uri": self._redirect_uri,
        }

        async with session.post(
            OAUTH2_TOKEN,
            data=token_data,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Token exchange failed: {resp.status} - {text}")

            tokens = await resp.json()

        self._access_token = tokens["access_token"]
        self._refresh_token = tokens["refresh_token"]

        _LOGGER.debug("Obtained access and refresh tokens")
