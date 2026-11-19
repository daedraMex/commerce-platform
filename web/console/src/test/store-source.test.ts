import { afterEach, describe, expect, it } from "vitest";

import {
  clearCurrentStore,
  getCurrentStore,
  setCurrentStore,
} from "@/lib/api/store-source";

afterEach(() => {
  clearCurrentStore();
});

describe("store source", () => {
  it("starts without a store", () => {
    expect(getCurrentStore()).toBeUndefined();
  });

  it("exposes the store taken from the current route params", () => {
    setCurrentStore("anime");
    expect(getCurrentStore()).toBe("anime");

    setCurrentStore("home");
    expect(getCurrentStore()).toBe("home");
  });

  it("clears the store when the route leaves the store scope", () => {
    setCurrentStore("anime");
    clearCurrentStore();
    expect(getCurrentStore()).toBeUndefined();
  });
});
