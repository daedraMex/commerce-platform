"""Permission codes a role may hold in a store (ADR-0021).

Pure Python: no Django, DRF or infrastructure imports belong here.
"""

PLACE_MANUAL_ORDER = "orders.place_manual"
REFUND_ORDER = "orders.refund"
ADJUST_INVENTORY = "inventory.adjust"
MANAGE_CATALOG = "catalog.manage"
APPROVE_SOCIAL_POST = "social.approve_post"
