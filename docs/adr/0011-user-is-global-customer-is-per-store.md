# A User is a global login, a Customer belongs to one store

A User is one login account for the whole platform, identified by an email that is unique across all stores; it is platform data, not a business table, so it is the deliberate exception to "every business table belongs to a Store" (ADR-0002). A Customer is a person who buys from one store, belongs to that store, and may exist without a User (a WhatsApp buyer, a guest checkout). The same person buying in `anime` and `home` is one User and two Customers, so each store owns its own customer data while a person keeps a single login.

## Considered Options

- Email unique per store (one User per store): rejected, because staff work across stores and a person would need a separate login and password per store.
- Customer as a flag or profile on User: rejected, because most WhatsApp and TikTok buyers never create a login.
