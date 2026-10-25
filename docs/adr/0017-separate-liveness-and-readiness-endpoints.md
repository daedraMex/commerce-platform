# Health is split into a liveness and a readiness endpoint

The API exposes two public health endpoints. `/api/v1/health/live/` checks no dependencies and returns 200 while the process runs; Dokploy uses it. `/api/v1/health/ready/` checks PostgreSQL and Redis and returns 200 with the result of each check, or 503 as problem details with `code: service_unavailable`. A single endpoint that checks dependencies would let a Redis outage make Dokploy restart or unroute an API that could still serve most requests.
