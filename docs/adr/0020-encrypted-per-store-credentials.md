---
status: accepted
---

# Per-store integration credentials are encrypted in the database

Integration credentials (Mercado Pago, TikTok Shop, Meta, WhatsApp) belong to a store, so they cannot be global environment variables, and adding a store must stay a data operation (ADR-0002). They are stored in PostgreSQL, one record per store and provider, encrypted with keys from their own setting, `CREDENTIALS_ENCRYPTION_KEYS`, a list that allows rotation (MultiFernet: encrypt with the first key, decrypt with any). This is never `SECRET_KEY`, so rotating `SECRET_KEY` never loses credentials. Code reads credentials only through a `CredentialStore` port (`get(store, provider)`), so an external secret manager can replace this implementation when the SaaS isolation model is chosen (ADR-0001). It is built in Phase 6, with its first consumer, Mercado Pago.

## Considered Options

- External secret manager (Infisical, Vault) with only a reference in the database: deferred, because it is one more service to run, secure and back up on a single VPS.
- Environment variables named per store: rejected, because every new store would need a redeploy.

## Consequences

- Losing the encryption keys loses every stored credential. The keys are backed up separately from the database; a database backup alone cannot restore credentials, and a leaked database backup alone does not expose them.
- ROADMAP DoD 3.4 now reads "encrypted at rest, with the key outside the database" instead of "never in the database".
