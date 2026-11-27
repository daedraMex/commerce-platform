---
status: accepted
---

# Phase 6a observes errors and liveness, and ships no logs yet

Phase 6a runs on one 2 vCPU VPS. Adding a log pipeline would mean another agent
container and a service to operate, so it waits. Instead, every container writes
structured JSON to stdout, Docker keeps it with bounded `json-file` rotation, and
Dokploy shows it; shipping can be added later without changing the log format.

Errors go to Sentry (Django, Celery, Quetzal) and alert Telegram only for new
issues and regressions. Better Stack monitors the API readiness endpoint and
Quetzal and holds dead-man's-switch heartbeats for the Celery beat sweep and the
daily backup, so a job that silently stops still alerts. A small VPS cron script
reports disk and memory to Telegram without a monitoring agent.

## Considered Options

- Ship logs to a hosted service now (Better Stack Logtail, Axiom): deferred
  until real traffic makes local Docker logs insufficient; it adds a vendor and,
  for a self-hosted option, another container on the same box.
- Self-hosted Loki/Grafana: rejected for 6a; too much to operate on a single
  2 vCPU VPS.

## Consequences

- Docker logs are for recent debugging, not long-term search; retention is
  bounded by rotation.
- The JSON log format is the contract that makes adding shipping later a
  configuration change, not a rewrite.
- Free-tier limits of Sentry and Better Stack are verified when their tickets
  are built, never hardcoded.
