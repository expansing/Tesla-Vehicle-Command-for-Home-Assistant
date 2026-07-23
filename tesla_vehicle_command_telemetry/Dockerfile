FROM tesla/fleet-telemetry:latest AS upstream

FROM debian:bookworm-slim

COPY --from=upstream /fleet-telemetry /fleet-telemetry
COPY run.sh /run.sh

RUN apt-get update \
	&& apt-get install --no-install-recommends -y ca-certificates \
	&& rm -rf /var/lib/apt/lists/* \
	&& chmod 755 /run.sh

CMD ["/run.sh"]