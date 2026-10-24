# Stores are data, and every business table belongs to a Store

The platform supports any number of stores. A store is a row, created with the `create_store` management command, never a name hardcoded in code, settings or branches. Every business table belongs to a Store, directly or through its parent, so that store scoping is structural rather than a convention each feature has to remember. This keeps adding a store a data operation and keeps every SaaS isolation option (ADR-0001) open.
