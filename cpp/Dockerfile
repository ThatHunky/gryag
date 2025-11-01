# syntax=docker/dockerfile:1

FROM debian:12 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       cmake \
       git \
       curl \
       pkg-config \
       tzdata \
       ca-certificates \
       openssl \
       libssl-dev \
       libcurl4-openssl-dev \
       sqlite3 \
       libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# Update CA certificates to ensure HTTPS works
RUN update-ca-certificates

WORKDIR /src
COPY . .

# Configure git to use proper SSL verification
RUN git config --global http.sslVerify true

RUN cmake -S cpp -B build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build -j"$(nproc)"

FROM debian:12-slim AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC \
    APP_HOME=/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libcurl4 \
       libssl3 \
       libsqlite3-0 \
       ca-certificates \
       tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR ${APP_HOME}

COPY --from=builder /src/build/bin/gryag-bot ${APP_HOME}/bin/gryag-bot
COPY db ${APP_HOME}/db
COPY personas ${APP_HOME}/personas
COPY response_templates ${APP_HOME}/response_templates

# Persist SQLite data under /app/data (mounted via volume)
RUN mkdir -p ${APP_HOME}/data

ENTRYPOINT ["/app/bin/gryag-bot"]
