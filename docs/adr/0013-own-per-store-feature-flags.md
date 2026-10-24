# Per-store feature flags are our own model, not a library

Feature flags are a small model of our own (store, flag code, enabled) behind a service that answers "is this flag on for this store?", built in Phase 3 right after Store exists. Libraries such as django-waffle target users, groups or percentages, not stores, and would push the store concept into a tool that does not know about it. Rollout rings (ADR-0001) are expressed as which stores have a flag on.
