FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl dbus gnupg iproute2 iptables procps tini \
    && rm -rf /var/lib/apt/lists/*

# Add Cloudflare WARP package repository
RUN mkdir -p /usr/share/keyrings \
    && curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg \
    | gpg --dearmor -o /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ bookworm main" \
    > /etc/apt/sources.list.d/cloudflare-warp.list \
    && apt-get update && apt-get install -y --no-install-recommends cloudflare-warp \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/warp
COPY scripts/warp/entrypoint.sh /opt/warp/entrypoint.sh
RUN chmod +x /opt/warp/entrypoint.sh

ENTRYPOINT ["/usr/bin/tini", "--", "/opt/warp/entrypoint.sh"]
