# Deployment notes

Operational requirements that the deployment must satisfy. The Phase 6 deployment
runbook (server hardening, Dokploy, backups, domains and TLS) will build on these notes.

## Database extensions

The catalog search is accent-insensitive and needs PostgreSQL's `unaccent` extension.
The `catalog` migration `0003_unaccent` runs `CREATE EXTENSION IF NOT EXISTS unaccent`.

The database role that runs migrations must therefore be allowed to run
`CREATE EXTENSION`, or a platform operator must create the extension in each environment
before migrating:

```sql
CREATE EXTENSION IF NOT EXISTS unaccent;
```

The migration is reversible: rolling it back drops the extension.
