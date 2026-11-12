export type MenuLabelKey =
  | "home"
  | "photos"
  | "inventory"
  | "orders"
  | "refunds"
  | "social";

export type MenuItem = {
  segment: string;
  labelKey: MenuLabelKey;
  permission: string | null;
};

export const MENU_ITEMS: readonly MenuItem[] = [
  { segment: "", labelKey: "home", permission: null },
  { segment: "photos", labelKey: "photos", permission: "catalog.manage" },
  { segment: "inventory", labelKey: "inventory", permission: "inventory.adjust" },
  { segment: "orders", labelKey: "orders", permission: "orders.place_manual" },
  { segment: "refunds", labelKey: "refunds", permission: "orders.refund" },
  { segment: "social", labelKey: "social", permission: "social.approve_post" },
];

export function menuItemsFor(permissions: readonly string[]): MenuItem[] {
  const allowed = new Set(permissions);
  return MENU_ITEMS.filter(
    (item) => item.permission === null || allowed.has(item.permission),
  );
}
