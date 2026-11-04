# One business today, SaaS later, with per-store feature flags

The platform runs for a single business today and is expected to become a SaaS. Our own stores are the first rollout ring: every new optional feature ships behind a per-store feature flag (core modules such as catalog, inventory and orders do not), is enabled for our stores first and rolled out to other stores afterwards. The SaaS isolation model (shared schema, schema per tenant, database per tenant) is deliberately not decided yet; it will be chosen later with real usage data, so nothing built now may assume one.
