---
status: accepted
---

# A category's attributes and options are declared in a small format of our own

A category declares, as JSON in a format we define, the attributes its products have and the options its variants differ on. An attribute is `{code, label, type, choices, required}`, where `type` is `text`, `number`, `boolean` or `choice`. An option is `{code, label, values}`, and each value is `{code, label}` plus its real dimensions in centimeters when the option is a size. Our own code validates a product's attributes and each variant's option values against its category: a variant has exactly one value per option, and no two variants of a product share the same values. The format is small enough for the platform operator to edit in the admin and maps directly to storefront filters.

## Considered Options

- JSON Schema validated with the `jsonschema` library: rejected, because it can express far more than we need, is hard to edit by hand, and does not say how to render a filter.
- Entity-attribute-value tables (`Attribute`, `AttributeValue`): rejected for now, because they add several models and admin screens before any query needs attributes in SQL.

## Consequences

- A new attribute type is a code change in our validator, not a schema keyword.
- A category with no options has products with exactly one variant.
- Option value codes are part of generated SKUs, so a product's options must be declared by its category, never chosen per product; a shape whose sizes differ (donut and rectangular pillows) is its own category.
- Moving to EAV later means migrating every product's attributes into rows, so it is done only when a real query needs it.
