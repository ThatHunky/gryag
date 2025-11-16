#!/usr/bin/env sh
set -euo pipefail

echo "==> Building dev services..."
docker compose build

echo "==> Building prod services..."
docker compose -f docker-compose.prod.yml build

echo "==> Dev bot healthcheck command:"
echo "    docker compose up -d bot && sleep 5 && docker compose ps bot"
echo "    # To inspect health: docker compose inspect bot | jq '.[0].State.Health'"

echo "==> Prod bot healthcheck command:"
echo "    docker compose -f docker-compose.prod.yml up -d bot && sleep 5 && docker compose -f docker-compose.prod.yml ps bot"
echo "    # To inspect health: docker compose -f docker-compose.prod.yml inspect bot | jq '.[0].State.Health'"


