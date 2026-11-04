# commerce-platform

A multi-store commerce platform: one backend serves any number of stores, their
storefront, and the AI agents that sell and publish on their behalf.

## Language

### Stores and rollout

**Store**:
A shop the platform sells through, with its own catalog, inventory, staff and theme. Stores are data, not code.
_Avoid_: Shop, brand, site, tenant

**Feature flag**:
A per-store switch that turns a feature on for one store without turning it on for the others.
_Avoid_: Toggle, setting

**Store-scoped**:
Said of an endpoint, query or task that acts on exactly one store and needs to know which one; everything else is global.
_Avoid_: Tenant-scoped, multi-tenant

**Integration credential**:
The secret a store uses to act on an external service in its own name, such as its payment or messaging account. It belongs to one store.
_Avoid_: API key, token, secret (as the name of the thing)

**Rollout ring**:
The group of stores a feature is enabled for at a given stage; our own stores are always the first ring.
_Avoid_: Beta group, cohort

### People and access

**User**:
A person's single login account on the platform, identified by an email that is unique across all stores, ignoring case.
_Avoid_: Account, login, profile

**Customer**:
A person who buys from one store; belongs to that store and may exist without a User. One User who buys in two stores is two Customers.
_Avoid_: Client, buyer, shopper

**Staff**:
The Users who hold a store membership in a store.
_Avoid_: Employee, admin, team member

**Platform operator**:
A person who runs the platform itself, above every store, and is not bound to any store membership.
_Avoid_: Superuser (outside code), admin

**Role**:
A named set of permissions from one platform-wide list, held by a staff member in one store. Owner is a role, not a separate kind of person.
_Avoid_: Group, profile

**Permission**:
The right to perform one kind of action, named by a code such as `orders.refund`.
_Avoid_: Privilege, capability, scope

**Store membership**:
The link that makes someone staff of one store, with exactly one role there. An inactive membership grants nothing.
_Avoid_: Assignment, employment

### Catalog

**Product**:
Something one store sells, described once and offered in one or more variants. The same design sold in two stores is two products, with separate stock.
_Avoid_: Item, article, listing

**Variant**:
One purchasable version of a product, distinguished from its siblings by its option values and identified by its SKU.
_Avoid_: SKU (as the name of the thing)

**Option**:
A dimension the variants of a product differ on, such as size or color; each variant has one value per option.
_Avoid_: Variation, attribute (for this)

**Attribute**:
A characteristic of a product that its category says it must or may have, such as material or care instructions; it is the same for every variant.
_Avoid_: Property, feature, spec

**SKU**:
The code that identifies a variant within its store, the same whatever its letter case.
_Avoid_: Barcode, reference

**Category**:
The type of a product, such as blankets or donut pillows, which defines the attributes and options its products have. Every product has exactly one.
_Avoid_: Product type, department

**Design**:
One artwork a store sells, identified by a design number that is never reused, and shared by every product made with it, such as the blanket and the pillow of the same artwork.
_Avoid_: Pattern, print, model

**Collection**:
A hand-picked group of a store's products that cuts across categories, such as a season or a theme; a product may be in several or none.
_Avoid_: Catalog, season, campaign

**Supplier**:
A business a store buys products from, such as a manufacturer whose designs the store resells.
_Avoid_: Vendor, provider, manufacturer (as the name of the thing)

### Inventory

**Location**:
A place where a store keeps stock, such as a warehouse or a shelf at home.
_Avoid_: Warehouse (unless it really is one), site

**Stock item**:
The quantity of one variant at one location.
_Avoid_: Stock (as a number on the variant), inventory record

**Stock movement**:
A recorded change to a stock item's quantity, with its reason.
_Avoid_: Adjustment (unless that is the reason), transaction

**Transfer**:
Moving stock between locations of different stores, recorded as an outbound stock movement in the source store and an inbound one in the destination store.
_Avoid_: Move, shipment

**Reservation**:
Stock held for an order that has not been paid yet, so it cannot be sold twice.
_Avoid_: Hold, lock, allocation

### Selling

**Order**:
A request to buy one or more variants from one store.
_Avoid_: Purchase, sale, cart

**Order item**:
One line of an order, keeping a copy of the variant's name, SKU and price at the time it was ordered.
_Avoid_: Line, order line

**Storefront**:
The single web application that shows each store to customers, themed for the store resolved from the domain.
_Avoid_: Web store, site, frontend (for this specifically)

**Theme**:
The visual identity a storefront takes on for one store.
_Avoid_: Skin, template

### Agents

**Agent**:
An AI worker the platform runs on behalf of a store, such as the Instagram publishing agent.
_Avoid_: Bot, assistant

**Agent definition**:
What an agent is: its handle, prompt, prompt version, model and allowed tools.
_Avoid_: Agent config, persona

**Handle**:
The name people use to @mention an agent, such as `@social`.
_Avoid_: Username, alias

**Agent run**:
One recorded execution of an agent, with its model, prompt version, tokens, latency and result.
_Avoid_: Job, call, invocation

**Handoff**:
Passing a conversation from an agent to a human, after which the agent stays silent.
_Avoid_: Escalation, transfer (that word is taken by inventory)
