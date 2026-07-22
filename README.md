# Tesla Vehicle Command

Home Assistant custom integration for Tesla Fleet API vehicle data and commands.

Tesla command authentication has four distinct parts:

1. Tesla OAuth lets Home Assistant access the account.
2. Tesla partner registration associates the Tesla developer app with a public domain and public command key.
3. A command key pair lets a vehicle authenticate commands end to end.
4. Tesla's `tesla-http-proxy` converts the Fleet API calls made by this integration into authenticated vehicle commands.

This guide configures all four parts using Home Assistant local add-ons, a minimal Nginx key server, and Cloudflare Tunnel. Replace every value in angle brackets with values from your own deployment.

## Before You Begin

You need:

- Home Assistant OS or Supervised, with access to a Terminal/SSH add-on.
- A Tesla account and an eligible Tesla vehicle.
- A Tesla Developer account at <https://developer.tesla.com>.
- A domain managed by Cloudflare.
- An HTTPS external URL for Home Assistant, such as `https://<ha-hostname>.<your-domain>`.
- A second hostname dedicated to Tesla's public key, such as `https://<tesla-key-hostname>.<your-domain>`.
- Cloudflare Tunnel connected to the Home Assistant network.

Do not reuse the Home Assistant hostname as the Tesla key hostname. The Tesla key endpoint must be public and unauthenticated, while Home Assistant should retain its normal authentication.

## Security Model

Only one file is public: the command **public** key at Tesla's required `.well-known` URL. It cannot be used to control a vehicle.

Never publish, upload, or paste a command **private** key, Tesla Client Secret, OAuth token, or Home Assistant configuration directory into a web server, Cloudflare Tunnel configuration, Git repository, issue report, or chat.

The local command proxy has no published host port. Do not add it to Cloudflare Tunnel or configure router port forwarding for it.

## 1. Create the Tesla Developer App

1. Open <https://developer.tesla.com> and create an **App**.
2. Add this redirect URI exactly:

   ```text
   https://<ha-hostname>.<your-domain>/auth/external/callback
   ```

3. Add this allowed origin exactly:

   ```text
   https://<tesla-key-hostname>.<your-domain>
   ```

4. Enable these scopes:

   ```text
   openid
   offline_access
   vehicle_device_data
   vehicle_cmds
   vehicle_charging_cmds
   ```

5. Save the **Client ID** and **Client Secret**. They are entered into Home Assistant later.

The redirect URI and allowed origin are separate values. The redirect URI points to Home Assistant; the allowed origin matches the public-key hostname exactly.

## 2. Generate the Command Key Pair

Run these commands in the Home Assistant Terminal/SSH add-on. They generate a NIST P-256 key pair compatible with Tesla vehicle command authentication.

```sh
mkdir -p /config/tesla_vehicle_command/keys /config/tesla_public
chmod 700 /config/tesla_vehicle_command/keys

openssl ecparam -name prime256v1 -genkey -noout \
  -out /config/tesla_vehicle_command/keys/tesla-command-private-key.pem
openssl ec -in /config/tesla_vehicle_command/keys/tesla-command-private-key.pem \
  -pubout \
  -out /config/tesla_public/com.tesla.3p.public-key.pem

chmod 600 /config/tesla_vehicle_command/keys/tesla-command-private-key.pem
chmod 755 /config/tesla_public
chmod 644 /config/tesla_public/com.tesla.3p.public-key.pem
```

The files have different purposes:

```text
/config/tesla_vehicle_command/keys/tesla-command-private-key.pem  Secret; import into the integration.
/config/tesla_public/com.tesla.3p.public-key.pem                  Public; serve this one file to Tesla.
```

Do not generate another key later. The public key hosted for Tesla, the private key imported into Home Assistant, and the key paired with the vehicle must all be the same key pair.

## 3. Create the Local Nginx Public-Key Add-on

Home Assistant discovers local add-ons under `/addons`. Create this directory structure on the Home Assistant host:

```text
/addons/tesla_key_server/
  config.yaml
  Dockerfile
  nginx.conf
```

Create `/addons/tesla_key_server/config.yaml`:

```yaml
name: Tesla public key server
version: "1.0.0"
slug: tesla_key_server
description: Serves only the Tesla Fleet API command public key.
arch:
  - aarch64
  - amd64
  - armv7
  - armhf
ports:
  8099/tcp: 8099
ports_description:
  8099/tcp: Tesla public key service; route through Cloudflare Tunnel only.
map:
  - config:ro
startup: services
boot: auto
```

Create `/addons/tesla_key_server/Dockerfile`:

```dockerfile
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
```

Create `/addons/tesla_key_server/nginx.conf`:

```nginx
server {
    listen 8099 default_server;
    server_name _;

    access_log off;
    error_log /dev/stderr warn;
    server_tokens off;
    autoindex off;

    location = /.well-known/appspecific/com.tesla.3p.public-key.pem {
        alias /config/tesla_public/com.tesla.3p.public-key.pem;
        default_type application/x-pem-file;
        add_header Cache-Control "public, max-age=3600" always;
        limit_except GET { deny all; }
    }

    location / {
        return 404;
    }
}
```

In Home Assistant, open **Settings > Add-ons > Add-on store**, select **Check for updates**, open **Local add-ons**, then install and start **Tesla public key server**.

Confirm the server exposes only the intended public key:

```sh
curl -i http://<home-assistant-lan-ip>:8099/.well-known/appspecific/com.tesla.3p.public-key.pem
curl -i http://<home-assistant-lan-ip>:8099/
```

The first response must be `200` and start with `-----BEGIN PUBLIC KEY-----`. The second response must be `404`.

## 4. Route the Key Server Through Cloudflare Tunnel

In Cloudflare Zero Trust:

1. Go to **Networks > Tunnels** and select the tunnel that can reach the Home Assistant network.
2. Add a public hostname: `<tesla-key-hostname>.<your-domain>`.
3. Set service type to `HTTP`.
4. Set the service URL to:

   ```text
   http://<home-assistant-lan-ip>:8099
   ```

   Use the Home Assistant host's LAN address. `localhost` works only when `cloudflared` runs in the same network namespace as the Nginx server.

5. Do not configure Cloudflare Access, login, redirects, or any authentication policy for this hostname.

Verify from outside the home network, for example using mobile data:

```sh
curl -i --max-time 10 \
  https://<tesla-key-hostname>.<your-domain>/.well-known/appspecific/com.tesla.3p.public-key.pem
```

It must return the public PEM directly with HTTP `200`. A Cloudflare error page, `524` timeout, redirect, or login page will prevent Tesla registration and vehicle pairing.

## 5. Register the Tesla Partner Account

Tesla Fleet API partner registration is regional. Use the region associated with your Tesla account:

```text
Europe:        https://fleet-api.prd.eu.vn.cloud.tesla.com
North America: https://fleet-api.prd.na.vn.cloud.tesla.com
```

Obtain a partner token in a trusted terminal. Set `FLEET_API_BASE_URL` to the regional endpoint selected above.

```sh
CLIENT_ID='<Tesla Client ID>'
CLIENT_SECRET='<Tesla Client Secret>'
FLEET_API_BASE_URL='https://fleet-api.prd.eu.vn.cloud.tesla.com'

PARTNER_TOKEN="$(
  curl -sS --request POST \
    --header 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode 'grant_type=client_credentials' \
    --data-urlencode "client_id=$CLIENT_ID" \
    --data-urlencode "client_secret=$CLIENT_SECRET" \
    --data-urlencode 'scope=openid vehicle_device_data vehicle_cmds vehicle_charging_cmds' \
    --data-urlencode "audience=$FLEET_API_BASE_URL" \
    'https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token' \
  | jq -r '.access_token'
)"
```

Register the public-key hostname. Do not include `https://` or a path.

```sh
curl -i --request POST \
  --header "Authorization: Bearer $PARTNER_TOKEN" \
  --header 'Content-Type: application/json' \
  --data '{"domain":"<tesla-key-hostname>.<your-domain>"}' \
  "$FLEET_API_BASE_URL/api/1/partner_accounts"
```

Tesla must be able to retrieve the public key from the hostname during registration. Keep the key service available permanently: Tesla may retrieve it again for key pairing or command validation.

## 6. Install the Local Tesla Vehicle Command Proxy Add-on

This repository includes a local add-on that runs Tesla's official `tesla/vehicle-command` Docker image. Copy this repository directory to the Home Assistant host:

```text
addons/tesla_vehicle_command_proxy/
```

The final files must be:

```text
/addons/tesla_vehicle_command_proxy/config.yaml
/addons/tesla_vehicle_command_proxy/Dockerfile
/addons/tesla_vehicle_command_proxy/run.sh
```

In Home Assistant, open **Settings > Add-ons > Add-on store**, select **Check for updates**, open **Local add-ons**, then install **Tesla Vehicle Command Proxy**. Enable **Start on boot** and start it.

The first log messages may say:

```text
Waiting for Tesla Vehicle Command integration files...
```

This is expected until the integration writes its local TLS material and command-key copy. The add-on is internal only. Never expose port `4443` through Cloudflare Tunnel, a reverse proxy, or router port forwarding.

## 7. Install and Configure the Integration

### Install

Install through HACS using this repository, or copy the integration files to:

```text
/config/custom_components/tesla_vehicle_command/
```

Restart Home Assistant after installation or updates.

### Configure

1. Open **Settings > Devices & services > Add integration**.
2. Select **Tesla Vehicle Command**.
3. Enter the Tesla Developer App Client ID and Client Secret.
4. Complete Tesla OAuth in the browser.
5. Select the vehicle or vehicles to add.
6. Choose **Import** and paste the complete content of:

   ```text
   /config/tesla_vehicle_command/keys/tesla-command-private-key.pem
   ```

   Include both PEM delimiters. A correct key begins with `-----BEGIN EC PRIVATE KEY-----` or `-----BEGIN PRIVATE KEY-----` and ends with the matching five-dash `END` line.

The integration creates the following private internal proxy files automatically:

```text
/config/tesla_vehicle_command/proxy-cert.pem
/config/tesla_vehicle_command/proxy-key.pem
/config/tesla_vehicle_command/proxy-ca.pem
/config/tesla_vehicle_command/proxy-command-key.pem
```

Do not edit these generated files. The integration and local proxy use the Supervisor DNS hostname `local-tesla-vehicle-command-proxy` internally.

## 8. Pair the Existing Command Key With the Vehicle

With the vehicle online and the Tesla mobile app signed in, open:

```text
https://tesla.com/_ak/<tesla-key-hostname>.<your-domain>?vin=<vehicle-vin>
```

Approve the enrollment prompt in the Tesla mobile app. The domain in this URL must exactly match the Tesla Developer App allowed origin and the hostname serving the public PEM.

If the vehicle reports that the public key is not paired, do not generate a replacement private key. Confirm the public PEM served at the `.well-known` endpoint was derived from the same private key imported in step 7, then repeat the enrollment link with the vehicle awake and online.

## Verify the Installation

1. The proxy add-on log includes `Listening on 0.0.0.0:4443`.
2. Home Assistant logs contain `Tesla Vehicle Command proxy is ready`.
3. Vehicle entities appear under **Settings > Devices & services**.
4. Vehicle data loads successfully. A `408 vehicle unavailable` means the vehicle is asleep or offline; wake it in the Tesla mobile app and retry.
5. Test a harmless command, such as flashing lights, only after the public key is paired.

## Metric Units

The integration reports values in metric units:

- Distance and range: `km`
- Speed: `km/h`
- Temperature: `°C`
- Tire pressure: `bar`
- Charge power: `kW`
- Added energy: `kWh`

## Troubleshooting

| Symptom | Resolution |
| --- | --- |
| `412 partner account must be registered` | Register the partner account using the correct Fleet API region and key hostname. |
| Cloudflare `524` or login page at the key URL | Fix the Tunnel origin; remove Cloudflare Access and redirects from the key hostname. |
| Proxy waits for integration files | Start or reload the integration and ensure the proxy add-on has `config:ro` mapping. |
| `invalid private key: expected PEM encoding` | Import the complete original P-256 private PEM, including both five-dash delimiter lines. |
| `certificate signed by unknown authority` from Fleet API | Rebuild the proxy add-on from this repository; its image installs `ca-certificates`. |
| `public key has not been paired with the vehicle` | Serve the public key matching the imported private key and repeat the Tesla enrollment link. |
| `408 vehicle unavailable` | The vehicle is offline or asleep. Wake it in the Tesla app and retry. |
| Proxy TLS `EOF` messages | Reload the integration and restart the proxy add-on after the integration has generated its TLS files. |

## References

- [Tesla Fleet API documentation](https://developer.tesla.com/docs/fleet-api)
- [Tesla partner endpoints](https://developer.tesla.com/docs/fleet-api/endpoints/partner-endpoints)
- [Tesla partner tokens](https://developer.tesla.com/docs/fleet-api/authentication/partner-tokens)
- [Tesla virtual-key developer guide](https://developer.tesla.com/docs/fleet-api/virtual-keys/developer-guide)
- [Tesla vehicle-command SDK](https://github.com/teslamotors/vehicle-command)
