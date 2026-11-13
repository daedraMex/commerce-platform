import { describe, expect, it } from "vitest";

import { MENU_ITEMS, menuItemsFor } from "@/lib/menu";

const segments = (permissions: string[]) =>
  menuItemsFor(permissions).map((item) => item.segment);

describe("permission-driven menu", () => {
  it("always shows home", () => {
    expect(segments([])).toEqual([""]);
  });

  it("shows the sections the permissions allow", () => {
    expect(segments(["catalog.manage", "inventory.adjust"])).toEqual([
      "",
      "photos",
      "inventory",
    ]);
  });

  it("ignores unknown permission codes", () => {
    expect(segments(["unrelated.permission"])).toEqual([""]);
  });

  it("derives visibility from permissions only, never from a role name", () => {
    const permissionCodes = MENU_ITEMS.flatMap((item) =>
      item.permission ? [item.permission] : [],
    );

    expect(segments(permissionCodes)).toEqual(
      MENU_ITEMS.map((item) => item.segment),
    );
    expect(MENU_ITEMS.some((item) => "role" in item)).toBe(false);
  });
});
