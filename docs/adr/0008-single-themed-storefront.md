# One themed Next.js storefront resolved by domain

There is a single Next.js storefront for all stores. The store, and therefore its theme, is resolved from the request domain; there is not one app per store. Adding a store must not require a new frontend project or deployment, consistent with stores being data (ADR-0002).
