---
status: accepted
---

# Catalog prices are MXN with IVA included, costs exclude IVA, and the catalog has no currency field

Every amount in the catalog is in Mexican pesos, as a decimal with two places. `price` and `compare_at_price` include IVA: they are what the customer pays, as Mexican consumer law requires the displayed price to be the total price (LFPC art. 7 Bis). `cost` is what we pay the supplier for one unit **without** IVA, because we credit the IVA we pay, so it is not part of what a unit costs us. There is no currency field on Store or Variant yet: our stores only sell in Mexico, and a currency that can never differ is a field every query would have to carry for nothing.

## Considered Options

- A currency field on Store or Variant now: deferred until a store sells outside Mexico, which is part of the SaaS decision (ADR-0001).
- Prices before IVA, with IVA added on top: rejected, because the price we enter, display and charge would always differ from the one stored.
- Cost with IVA included: rejected, because the IVA we pay is credited, so including it would understate every margin.

## Consequences

- `price` and `cost` are on different bases: a unit's margin is `price / 1.16 - cost` (at the general 16% rate), never `price - cost`.
- Orders (Phase 5) record `currency` as MXN and compute `tax_total` by breaking IVA out of IVA-included prices, never by adding it; the `unit_cost` copied into an order item is before IVA.
- Supporting another currency later means adding the field with MXN as the value for every existing row.
