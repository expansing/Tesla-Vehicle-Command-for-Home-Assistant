#!/bin/sh
set -eu

CONFIG_DIR=/config/tesla_vehicle_command
CERT_FILE="$CONFIG_DIR/telemetry-cert.pem"
KEY_FILE="$CONFIG_DIR/telemetry-key.pem"
CLIENT_CA_FILE="$CONFIG_DIR/telemetry-ca.pem"
CONFIG_FILE=/tmp/fleet-telemetry-config.json
receiver_pid=""

shutdown() {
    if [ -n "$receiver_pid" ]; then
        kill -TERM "$receiver_pid" 2>/dev/null || true
        wait "$receiver_pid" 2>/dev/null || true
    fi
    exit 0
}

trap shutdown INT TERM

while [ ! -r "$CERT_FILE" ] || [ ! -r "$KEY_FILE" ] || [ ! -r "$CLIENT_CA_FILE" ]; do
    echo "Waiting for Tesla Fleet Telemetry certificate files..."
    sleep 2
done

cat > "$CONFIG_FILE" <<EOF
{
  "host": "0.0.0.0",
  "port": 4443,
  "status_port": 8080,
  "log_level": "info",
  "json_log_enable": true,
  "namespace": "tesla_telemetry",
  "transmit_decoded_records": true,
  "rate_limit": {
    "enabled": true,
    "message_interval_time": 30,
    "message_limit": 1000
  },
  "records": {
    "V": ["zmq"],
    "alerts": ["logger"],
    "errors": ["logger"],
    "connectivity": ["zmq", "logger"]
  },
  "zmq": {
    "addr": "tcp://*:5284"
  },
  "tls": {
    "server_cert": "$CERT_FILE",
    "server_key": "$KEY_FILE",
    "client_ca": "$CLIENT_CART_FILE",
    "server_key": "$KEY_FILE",
    "client_ca": "$CLIENT_CA_FILE"
  }
}
EOF

while true; do
    /fleet-telemetry -config "$CONFIG_FILE" &
    receiver_pid=$!
    if wait "$receiver_pid"; then
        receiver_pid=""
        exit 0
    fi
    receiver_pid=""
    echo "Tesla Fleet Telemetry receiver exited; retrying in 2 seconds..."
    sleep 2
done