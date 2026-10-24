# Inventory is per store and addressed by Location

Stock belongs to a store and is always addressed by Location: a StockItem is a variant at a location, never a single stock number on the variant. A transfer between stores is recorded as an outbound movement in the source store and an inbound movement in the destination store, not as one movement shared by two stores, so that no inventory record ever belongs to more than one store.
