# Tesla Vehicle Command - Home Assistant Integration Setup Guide

## Prerequisites

### 1. Tesla Developer Account
1. Go to https://developer.tesla.com
2. Sign in with your Tesla account
3. Create a new **App** (not "Product")
4. Configure:
   - **App Name**: "Home Assistant Tesla Command" (or your choice)
   - **Redirect URI**: `https://YOUR_HA_URL.local/auth/external/callback`
     - Replace `YOUR_HA_URL` with your Home Assistant external URL
     - Must use HTTPS
     - Must match exactly what you'll enter in HA
   - **Scopes**: Select all:
     - `openid`
     - `offline_access`
     - `vehicle_device_data`
     - `vehicle_cmds`
     - `vehicle_charging_cmds`
5. Save and note down:
   - **Client ID**
   - **Client Secret**

### 2. Home Assistant Requirements
- Home Assistant 2024.6 or later
- External HTTPS access (required for OAuth callback)
  - Nabu Casa Cloud, or
  - Reverse proxy (nginx, Caddy, Traefik) with valid SSL cert
- HACS (Home Assistant Community Store) installed

### 3. Vehicle Requirements
- **2019 Model 3** ✅ Supported
- Tesla mobile app installed on your phone
- Vehicle connected to WiFi/cellular

---

## Installation

### Option A: HACS (Recommended)
1. Open HACS in Home Assistant
2. Click "Integrations" → Three dots → "Custom repositories"
3. Add repository: `https://github.com/teslamotors/vehicle-command` (or your fork)
   - Category: "Integration"
4. Search for "Tesla Vehicle Command" and install
5. Restart Home Assistant

### Option B: Manual
1. Copy the `tesla_vehicle_command` folder to:
   ```
   <config>/custom_components/tesla_vehicle_command/
   ```
2. Restart Home Assistant

---

## Configuration

### Step 1: Add Integration
1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for "Tesla Vehicle Command"
3. Enter your **Client ID** and **Client Secret** from Tesla Developer portal
4. Click **Submit**

### Step 2: Authorize with Tesla
1. You'll be redirected to Tesla's login page
2. Sign in with your Tesla account
3. Grant permissions to the app
4. You'll be redirected back to Home Assistant

### Step 3: Select Vehicles
1. Choose which vehicle(s) to add (your 2019 Model 3)
2. Click **Submit**

### Step 4: Generate/Import Private Key
1. **Generate New Key** (recommended):
   - Click "Generate" - creates a new ECDH key pair
   - Save the private key path shown
2. **Or Import Existing Key**:
   - Paste your PEM-formatted private key

### Step 5: Enroll Key in Tesla App ⚠️ CRITICAL STEP
1. Open **Tesla Mobile App**
2. Go to **Security** → **Vehicle Commands** → **Add Key**
3. Scan the QR code or enter the key manually
   - The integration will show you the public key fingerprint
4. Approve on your vehicle's touchscreen (sit in car)
5. Key enrollment complete!

---

## Entities Created

### Sensors (30+)
| Entity | Description |
|--------|-------------|
| `sensor.model_3_battery_level` | Battery % |
| `sensor.model_3_battery_range` | Estimated range (miles) |
| `sensor.model_3_charging_state` | Charging/Complete/Disconnected |
| `sensor.model_3_charge_limit` | Charge limit % |
| `sensor.model_3_inside_temp` | Cabin temperature |
| `sensor.model_3_outside_temp` | Outside temperature |
| `sensor.model_3_odometer` | Total miles |
| `sensor.model_3_locked` | Door lock state |
| `sensor.model_3_sentry_mode` | Sentry mode state |
| `sensor.model_3_tpms_fl/fr/rl/rr` | Tire pressures |

### Climate
| Entity | Description |
|--------|-------------|
| `climate.model_3` | HVAC control (on/off, temperature) |

### Lock
| Entity | Description |
|--------|-------------|
| `lock.model_3_door_lock` | Lock/unlock doors |

### Covers
| Entity | Description |
|--------|-------------|
| `cover.model_3_trunk` | Rear trunk (open/close) |
| `cover.model_3_frunk` | Front trunk (open only) |
| `cover.model_3_windows` | All windows (vent/close) |
| `cover.model_3_sunroof` | Sunroof (position 0-100%) |

### Switches
| Entity | Description |
|--------|-------------|
| `switch.model_3_sentry_mode` | Sentry mode on/off |
| `switch.model_3_charge_port` | Charge port open/close |
| `switch.model_3_defrost` | Max defrost |

### Numbers
| Entity | Description |
|--------|-------------|
| `number.model_3_charge_limit` | Charge limit 50-100% |
| `number.model_3_target_temperature` | Climate temp 15-28°C |

### Selects
| Entity | Description |
|--------|-------------|
| `select.model_3_front_left_seat_heater` | Off/Low/Med/High |
| `select.model_3_steering_heater` | Off/On |

### Buttons ⭐
| Entity | Description |
|--------|-------------|
| `button.model_3_wake_up` | Wake vehicle |
| `button.model_3_honk_horn` | Honk horn |
| `button.model_3_flash_lights` | Flash lights |
| `button.model_3_open_charge_port` | Open charge port |
| `button.model_3_close_charge_port` | Close charge port |
| `button.model_3_open_trunk` | Open rear trunk |
| `button.model_3_open_frunk` | Open frunk |
| `button.model_3_vent_windows` | Vent windows |
| `button.model_3_close_windows` | Close windows |
| `button.model_3_preconditioning_start` | **Start battery preconditioning** |
| `button.model_3_preconditioning_stop` | **Stop battery preconditioning** |

---

## Services

Call from automations/scripts:
```yaml
# Set valet mode
service: tesla_vehicle_command.set_valet_mode
data:
  vin: "5YJ3E1EBXMF123456"
  enabled: true
  pin: "1234"

# Set speed limit
service: tesla_vehicle_command.set_speed_limit
data:
  vin: "5YJ3E1EBXMF123456"
  speed_limit: 120
  pin: "1234"

# Send navigation
service: tesla_vehicle_command.send_navigation
data:
  vin: "5YJ3E1EBXMF123456"
  latitude: 37.7749
  longitude: -122.4194
  name: "San Francisco"
```

---

## Troubleshooting

### "Proxy failed to start"
- Check logs: `Settings` → `System` → `Logs` → Filter "tesla_vehicle_command"
- Ensure architecture matches (amd64/arm64)
- Try manual binary download from GitHub releases

### "Vehicle not responding"
- Wake vehicle first: `button.model_3_wake_up`
- Check vehicle has cellular/WiFi
- Verify key enrollment in Tesla app

### "Token refresh failed"
- Re-authenticate: Remove integration → Add again
- Check Client Secret is correct

### "Command timeout"
- Vehicle may be asleep - wake it first
- Increase proxy timeout in config (advanced)

---

## Architecture

```
Home Assistant (Python)
    │
    ├── Config Flow (OAuth2 + Key Gen)
    ├── Coordinator (Polls vehicle data)
    ├── Entities (Sensors, Climate, Lock, etc.)
    │
    └── Proxy Manager
            │
            ▼
    tesla-http-proxy (Go binary)
            │
            ├── TLS (localhost:4443)
            ├── Private Key (command auth)
            └── OAuth Token (Fleet API auth)
                    │
                    ▼
            Tesla Fleet API → Vehicle
```

---

## Security Notes

- Private keys stored in `<config>/tesla_vehicle_command/keys/` (chmod 600)
- OAuth tokens encrypted in HA config entry storage
- Proxy binds to **localhost only** (no external exposure)
- Self-signed TLS certs for local proxy communication
- Key enrollment requires physical access to vehicle

---

## Updating

### HACS
- HACS → Integrations → Tesla Vehicle Command → Update

### Manual
- Replace `custom_components/tesla_vehicle_command/` folder
- Restart Home Assistant

---

## Support

- **Issues**: https://github.com/teslamotors/vehicle-command/issues
- **Discord**: Tesla Developer Community
- **Docs**: https://developer.tesla.com/docs/fleet-api