"""Proxy manager for tesla-http-proxy binary."""

from __future__ import annotations

import asyncio
import datetime
import ipaddress
import logging
import os
import platform
import shutil
import ssl
import tempfile
from pathlib import Path

import aiohttp
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography import x509
from cryptography.x509.oid import NameOID
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    GITHUB_RELEASES_API,
    PROXY_BINARIES,
    PROXY_HOST,
    PROXY_PORT,
    PROXY_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class ProxyManager:
    """Manage the tesla-http-proxy binary lifecycle."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the proxy manager."""
        self.hass = hass
        self.entry = entry
        self._process: asyncio.subprocess.Process | None = None
        self._binary_path: Path | None = None
        self._cert_path: Path | None = None
        self._key_path: Path | None = None
        self._ca_path: Path | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        """Return if proxy is running."""
        return self._running and self._process is not None and self._process.returncode is None

    @property
    def binary_path(self) -> Path | None:
        """Return the binary path."""
        return self._binary_path

    @property
    def cert_path(self) -> Path | None:
        """Return the CA cert path for clients."""
        return self._ca_path

    async def async_start(self) -> None:
        """Start the proxy."""
        if self.is_running:
            return

        # Get config directory
        config_dir = Path(self.hass.config.path(DOMAIN))
        config_dir.mkdir(parents=True, exist_ok=True)

        # Download/verify binary
        self._binary_path = await self._ensure_binary(config_dir)

        # Generate TLS certificates
        self._cert_path, self._key_path, self._ca_path = await self._ensure_certificates(config_dir)

        # Get private key path from config
        private_key_path = self.entry.data.get("private_key_path")
        if not private_key_path or not Path(private_key_path).exists():
            _LOGGER.error("Private key not found at %s", private_key_path)
            return

        # Start proxy process
        env = os.environ.copy()
        env["TESLA_HTTP_PROXY_TLS_CERT"] = str(self._cert_path)
        env["TESLA_HTTP_PROXY_TLS_KEY"] = str(self._key_path)
        env["TESLA_HTTP_PROXY_HOST"] = PROXY_HOST
        env["TESLA_HTTP_PROXY_PORT"] = str(PROXY_PORT)
        env["TESLA_HTTP_PROXY_TIMEOUT"] = str(PROXY_TIMEOUT)
        env["TESLA_VERBOSE"] = "true"

        cmd = [
            str(self._binary_path),
            "-key-file", private_key_path,
        ]

        _LOGGER.info("Starting tesla-http-proxy: %s", " ".join(cmd))
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Read stdout/stderr in background
        asyncio.create_task(self._read_output(self._process.stdout, "stdout"))
        asyncio.create_task(self._read_output(self._process.stderr, "stderr"))

        # Wait for proxy to be ready
        await self._wait_for_ready()

    async def _read_output(self, stream: asyncio.StreamReader, name: str) -> None:
        """Read process output."""
        while True:
            line = await stream.readline()
            if not line:
                break
            _LOGGER.debug("[proxy %s] %s", name, line.decode().rstrip())

    async def _wait_for_ready(self, timeout: float = 10.0) -> None:
        """Wait for proxy to be ready."""
        import time
        start = time.time()
        session = async_get_clientsession(self.hass)

        # Create SSL context that trusts our CA
        ssl_context = ssl.create_default_context()
        ssl_context.load_verify_locations(self._ca_path)

        while time.time() - start < timeout:
            if self._process.returncode is not None:
                stderr = await self._process.stderr.read() if self._process.stderr else b""
                raise RuntimeError(f"Proxy exited with code {self._process.returncode}: {stderr.decode()}")

            try:
                async with session.get(
                    f"https://{PROXY_HOST}:{PROXY_PORT}/health",
                    ssl=ssl_context,
                    timeout=aiohttp.ClientTimeout(total=2),
                ) as resp:
                    if resp.status == 200:
                        self._running = True
                        _LOGGER.info("Tesla HTTP proxy started on https://%s:%d", PROXY_HOST, PROXY_PORT)
                        return
            except Exception:
                pass

            await asyncio.sleep(0.5)

        raise TimeoutError("Proxy did not become ready in time")

    async def async_stop(self) -> None:
        """Stop the proxy."""
        if self._process and self._process.returncode is None:
            _LOGGER.info("Stopping tesla-http-proxy")
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
        self._running = False

    async def _ensure_binary(self, config_dir: Path) -> Path:
        """Ensure the proxy binary exists."""
        system = platform.system().lower()
        machine = platform.machine().lower()

        # Normalize machine names
        if machine in ("x86_64", "amd64"):
            machine = "amd64"
        elif machine in ("aarch64", "arm64"):
            machine = "arm64"

        binary_name = PROXY_BINARIES.get((system, machine))
        if not binary_name:
            raise RuntimeError(f"No binary available for {system}/{machine}")

        binary_path = config_dir / binary_name

        if binary_path.exists():
            # Verify checksum
            if await self._verify_binary(binary_path):
                _LOGGER.info("Using existing proxy binary: %s", binary_path)
                return binary_path
            _LOGGER.warning("Binary checksum mismatch, re-downloading")

        # Download from GitHub releases
        _LOGGER.info("Downloading proxy binary: %s", binary_name)
        await self._download_binary(binary_name, binary_path)

        # Make executable
        binary_path.chmod(0o755)

        # Verify
        if not await self._verify_binary(binary_path):
            raise RuntimeError("Downloaded binary failed verification")

        return binary_path

    async def _verify_binary(self, binary_path: Path) -> bool:
        """Verify binary checksum."""
        # TODO: Implement checksum verification from GitHub releases
        return True

    async def _download_binary(self, binary_name: str, dest_path: Path) -> None:
        """Download binary from GitHub releases."""
        session = async_get_clientsession(self.hass)

        # Get latest release
        async with session.get(GITHUB_RELEASES_API) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Failed to fetch releases: {resp.status}")
            release = await resp.json()

        # Find asset
        asset_url = None
        for asset in release.get("assets", []):
            if asset["name"] == binary_name:
                asset_url = asset["browser_download_url"]
                break

        if not asset_url:
            raise RuntimeError(f"Binary {binary_name} not found in release")

        # Download
        async with session.get(asset_url) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Failed to download binary: {resp.status}")
            content = await resp.read()

        # Write to temp then move
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            shutil.move(str(tmp_path), str(dest_path))
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    async def _ensure_certificates(self, config_dir: Path) -> tuple[Path, Path, Path]:
        """Generate or load TLS certificates."""
        cert_path = config_dir / "proxy-cert.pem"
        key_path = config_dir / "proxy-key.pem"
        ca_path = config_dir / "proxy-ca.pem"

        if cert_path.exists() and key_path.exists() and ca_path.exists():
            _LOGGER.info("Using existing TLS certificates")
            return cert_path, key_path, ca_path

        _LOGGER.info("Generating TLS certificates for proxy")

        # Generate CA
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Tesla Vehicle Command CA")])
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(ca_name)
            .issuer_name(ca_name)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(
                    key_cert_sign=True,
                    crl_sign=True,
                    digital_signature=False,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .sign(ca_key, hashes.SHA256())
        )

        # Generate server cert
        server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        server_cert = (
            x509.CertificateBuilder()
            .subject_name(server_name)
            .issuer_name(ca_name)
            .public_key(server_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                ]),
                critical=False,
            )
            .add_extension(
                x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
                critical=True,
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    key_encipherment=True,
                    content_commitment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .sign(ca_key, hashes.SHA256())
        )

        # Write files
        ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
        cert_path.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(server_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))

        # Secure permissions
        key_path.chmod(0o600)
        ca_path.chmod(0o644)
        cert_path.chmod(0o644)

        return cert_path, key_path, ca_path
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
            self._process = None

        self._running = False
        _LOGGER.info("Tesla HTTP proxy stopped")

    async def _ensure_binary(self) -> None:
        """Ensure the proxy binary exists, download if needed."""
        # Determine platform
        system = platform.system().lower()
        machine = platform.machine().lower()

        if system == "linux" and machine in ("x86_64", "amd64"):
            binary_key = "linux_x86_64"
        elif system == "linux" and machine in ("aarch64", "arm64"):
            binary_key = "linux_aarch64"
        elif system == "darwin" and machine in ("x86_64", "amd64"):
            binary_key = "darwin_x86_64"
        elif system == "darwin" and machine in ("arm64", "aarch64"):
            binary_key = "darwin_arm64"
        elif system == "windows" and machine in ("x86_64", "amd64"):
            binary_key = "win32"
        else:
            raise RuntimeError(f"Unsupported platform: {system}/{machine}")

        binary_name = PROXY_BINARIES[binary_key]
        binary_dir = Path(self.hass.config.path(DOMAIN, "bin"))
        binary_dir.mkdir(parents=True, exist_ok=True)
        self._binary_path = binary_dir / binary_name

        if self._binary_path.exists():
            _LOGGER.debug("Proxy binary already exists: %s", self._binary_path)
            return

        # Download from GitHub releases
        _LOGGER.info("Downloading tesla-http-proxy for %s", binary_key)
        await self._download_binary(binary_key, binary_name)

        # Make executable
        self._binary_path.chmod(0o755)

    async def _download_binary(self, binary_key: str, binary_name: str) -> None:
        """Download binary from GitHub releases."""
        session = async_get_clientsession(self.hass)

        # Get latest release info
        async with session.get(GITHUB_RELEASES_API) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Failed to fetch release info: {resp.status}")
            release = await resp.json()

        # Find asset
        asset = None
        for a in release.get("assets", []):
            if a["name"] == binary_name:
                asset = a
                break

        if not asset:
            raise RuntimeError(f"Binary {binary_name} not found in release")

        # Download
        download_url = asset["browser_download_url"]
        _LOGGER.info("Downloading from %s", download_url)

        async with session.get(download_url) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Failed to download binary: {resp.status}")

            content = await resp.read()

            # Verify checksum if available
            # TODO: Add checksum verification

            # Write binary
            with open(self._binary_path, "wb") as f:
                f.write(content)

        _LOGGER.info("Downloaded proxy binary to %s", self._binary_path)

    async def _generate_certificates(self) -> None:
        """Generate self-signed TLS certificates for proxy."""
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime

        cert_dir = Path(self.hass.config.path(DOMAIN, "certs"))
        cert_dir.mkdir(parents=True, exist_ok=True)

        self._cert_path = cert_dir / "proxy-cert.pem"
        self._key_path = cert_dir / "proxy-key.pem"
        self._ca_path = cert_dir / "ca-cert.pem"

        if self._cert_path.exists() and self._key_path.exists() and self._ca_path.exists():
            _LOGGER.debug("TLS certificates already exist")
            return

        # Generate CA
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Tesla Vehicle Command CA")])
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(ca_name)
            .issuer_name(ca_name)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(key_cert_sign=True, crl_sign=True, digital_signature=False, content_commitment=False, key_encipherment=False, data_encipherment=False, key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
            .sign(ca_key, hashes.SHA256())
        )

        # Generate server cert
        server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        server_cert = (
            x509.CertificateBuilder()
            .subject_name(server_name)
            .issuer_name(ca_name)
            .public_key(server_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=True, key_cert_sign=False, crl_sign=False, content_commitment=False, data_encipherment=False, key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
            .sign(ca_key, hashes.SHA256())
        )

        # Write files
        with open(self._ca_path, "wb") as f:
            f.write(ca_cert.public_bytes(serialization.Encoding.PEM))

        with open(self._cert_path, "wb") as f:
            f.write(server_cert.public_bytes(serialization.Encoding.PEM))

        with open(self._key_path, "wb") as f:
            f.write(server_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ))

        # Combine cert + CA for proxy
        with open(self._cert_path, "ab") as f:
            f.write(ca_cert.public_bytes(serialization.Encoding.PEM))

        _LOGGER.info("Generated TLS certificates in %s", cert_dir)

    async def _start_proxy(self, private_key_path: str) -> None:
        """Start the proxy process."""
        if not self._binary_path or not self._cert_path or not self._key_path:
            raise RuntimeError("Binary or certificates not ready")

        cmd = [
            str(self._binary_path),
            "-port", str(PROXY_PORT),
            "-host", PROXY_HOST,
            "-cert", str(self._cert_path),
            "-tls-key", str(self._key_path),
            "-key-file", private_key_path,
        ]

        _LOGGER.info("Starting proxy: %s", " ".join(cmd))

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Log output
        asyncio.create_task(self._log_output())

        self._running = True

    async def _log_output(self) -> None:
        """Log proxy stdout/stderr."""
        if not self._process:
            return

        async def read_stream(stream: asyncio.StreamReader, prefix: str) -> None:
            while True:
                line = await stream.readline()
                if not line:
                    break
                _LOGGER.debug("[proxy %s] %s", prefix, line.decode().rstrip())

        await asyncio.gather(
            read_stream(self._process.stdout, "stdout"),
            read_stream(self._process.stderr, "stderr"),
        )

    async def _wait_for_ready(self, timeout: float = 10.0) -> None:
        """Wait for proxy to be ready."""
        import aiohttp

        start = asyncio.get_event_loop().time()
        ssl_context = ssl.create_default_context()
        if self._ca_path:
            ssl_context.load_verify_locations(str(self._ca_path))

        while asyncio.get_event_loop().time() - start < timeout:
            if not self.is_running:
                raise RuntimeError("Proxy process died")

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{self.proxy_url}/health",
                        ssl=ssl_context,
                        timeout=aiohttp.ClientTimeout(total=2),
                    ) as resp:
                        if resp.status == 200:
                            _LOGGER.info("Proxy is ready")
                            return
            except Exception:
                pass

            await asyncio.sleep(0.5)

        raise RuntimeError("Proxy did not become ready in time")