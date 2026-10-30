---
status: accepted
---

# Port implementations are wired in one composition root through provider functions

`apps/shared` defines ports such as `StoreResolver`, `Authorizer` and `FeatureFlags`, but must not import the modules that implement them. `config/dependencies.py` is the single place that knows which implementation backs each port, and it exposes provider functions (`get_store_resolver()`, `get_authorizer()`, `get_feature_flags()`), never objects built at import time. Views, mixins and use-case wiring call a provider when they need the port, so there are no circular imports, and tests replace a provider with a fixture instead of patching module attributes.

## Considered Options

- One dotted-path setting per port: rejected, because the wiring would be spread across settings and resolved by string, with no single place to read it.
- Module-level instances: rejected, because building them at import time invites circular imports and forces tests to patch modules.
