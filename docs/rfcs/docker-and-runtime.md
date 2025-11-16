# RFC: Docker and Runtime

Status: Proposed

Problem
- Ensure dev/prod parity, small images, and health checks. Align docs and Make targets with `docker compose` for the `bot` service.

Evidence
- `docker-compose.yml`, `Dockerfile` present; `docker compose up bot` recommended.

Options
1. Document image build strategy (multi-stage), caching, and runtime envs.
2. Add healthcheck for bot liveness, and logs volume guidance.

Recommendation
- Adopt (1) and (2). Provide guidance on mounting `.env`, persistent volumes (logs, redis), and tagging strategy.

Impact
- Smoother deployments and debugging.

Effort
- S.

Risks
- None.

Acceptance Criteria
- Docs list compose targets, healthcheck example, and environment variable mapping.


