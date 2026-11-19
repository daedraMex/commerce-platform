import { render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { StoreRoute } from "@/components/providers/store-route";
import {
  clearCurrentStore,
  getCurrentStore,
  setCurrentStore,
} from "@/lib/api/store-source";

afterEach(() => {
  clearCurrentStore();
});

describe("store route source", () => {
  it("sets the store on commit and clears it when the subtree unmounts", () => {
    const view = render(
      <StoreRoute store="anime">
        <span>content</span>
      </StoreRoute>,
    );

    expect(getCurrentStore()).toBe("anime");

    view.unmount();

    expect(getCurrentStore()).toBeUndefined();
  });

  it("does not clear a store that a newer route already owns", () => {
    const view = render(
      <StoreRoute store="anime">
        <span>content</span>
      </StoreRoute>,
    );

    setCurrentStore("home");
    view.unmount();

    expect(getCurrentStore()).toBe("home");
  });
});
