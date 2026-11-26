---
status: accepted
---

# Payment and shipping providers are swappable adapters chosen per store, and the domain never speaks their language

Payments (Phase 6) and shipping (Phase 6b) are modules with business rules and clean architecture. Each reaches its external service through one port, `PaymentGateway` for Mercado Pago and `ShippingProvider` for Envíosperros, and its domain uses our own terms: payment, external reference, shipping quote, shipment, carrier, shipping label. The adapter is the only code that knows the provider's identifiers, statuses and formats, and maps them both ways. A payment or a shipment keeps the provider's id only as an external reference, next to the provider's name, and never uses it as our own id. Which provider a store uses is a per-store setting, so replacing Mercado Pago or Envíosperros means adding an adapter behind the port, not changing orders or checkout.

Today the four stores share one Mercado Pago account and one Envíosperros account. Each store still has its own integration credential for each provider (ADR-0020), and today all four hold the same secret, so moving one store to its own account later is a credential change, not a code change.

## Considered Options

- Call Mercado Pago and Envíosperros directly from orders and checkout: rejected. The provider's ids and statuses would spread into orders, and replacing a provider would touch every module that ships or charges.
- One global setting for the provider and one global credential: rejected. It breaks ADR-0020, and moving one store to another account or provider would need a code change.

## Consequences

- `shipping` joins the list of modules with clean architecture in `AGENTS.md`.
- Our records never depend on a provider's format: a provider's id is stored only as an external reference with the provider's name, so an order that was charged or shipped by a provider we no longer use still reads correctly.
- Each new provider is one adapter with a fake implementation for the tests, following ROADMAP section 3.4.
- Deployment moved from Phase 6 to Phase 6a, right after Phase 4b, so staging exists before payments; this changes only when ADR-0026's "nothing is deployed until Phase 6" happens, not how Quetzal is deployed.
