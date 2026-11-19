import { afterEach, describe, expect, it } from "vitest";

import {
  bindStoreToSignal,
  clearCurrentStore,
  getCurrentStore,
  getStoreFromSignal,
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

  it("only clears the store it owns", () => {
    setCurrentStore("anime");

    clearCurrentStore("home");
    expect(getCurrentStore()).toBe("anime");

    clearCurrentStore("anime");
    expect(getCurrentStore()).toBeUndefined();
  });

  it("binds a store to the signal of the query it owns", () => {
    const controller = new AbortController();

    bindStoreToSignal(controller.signal, "anime");

    expect(getStoreFromSignal(controller.signal)).toBe("anime");
  });

  it("has no store for an unbound or missing signal", () => {
    expect(getStoreFromSignal(new AbortController().signal)).toBeUndefined();
    expect(getStoreFromSignal(undefined)).toBeUndefined();
  });
});
