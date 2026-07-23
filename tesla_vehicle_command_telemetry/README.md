# Tesla Fleet Telemetry Receiver

This Home Assistant add-on runs Tesla's official Fleet Telemetry receiver.
It accepts an inbound mTLS connection from the vehicle on TCP port `4443` and
keeps decoded telemetry on an internal ZMQ endpoint. The ZMQ endpoint is not
published as a Home Assistant add-on port.

Before starting the add-on, configure the integration's Fleet Telemetry
hostname and port, then reload the integration. The integration writes the
dedicated telemetry certificate files under
`/config/tesla_vehicle_command/`. Route the configured public hostname and
TCP port to this add-on, then invoke the
`tesla_vehicle_command.configure_fleet_telemetry` service for each vehicle.

The hostname must resolve publicly and reach this add-on directly. Do not use
the command-proxy hostname or its certificate files for the telemetry receiver.