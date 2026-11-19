import { describe, expect, it } from "vitest";

import {
  isStoreDetailPath,
  isStoreSegment,
  storeHref,
  storeSlugFromPathname,
  swapStoreInPath,
} from "@/lib/store-path";

describe("storeSlugFromPathname", () => {
  it("reads the first path segment as the store", () => {
    expect(storeSlugFromPathname("/anime")).toBe("anime");
    expect(storeSlugFromPathname("/anime/photos")).toBe("anime");
    expect(storeSlugFromPathname("/anime/photos?from=menu")).toBe("anime");
  });

  it("ignores routes that are not store scoped", () => {
    expect(storeSlugFromPathname("/")).toBeUndefined();
    expect(storeSlugFromPathname("/sign-in")).toBeUndefined();
    expect(storeSlugFromPathname("/sign-in?next=%2Fanime")).toBeUndefined();
    expect(storeSlugFromPathname("/api/backend/api/v1/me/")).toBeUndefined();
    expect(storeSlugFromPathname("/_next/static/chunk.js")).toBeUndefined();
  });
});

describe("swapStoreInPath", () => {
  it("replaces only the store segment", () => {
    expect(swapStoreInPath("/anime", "home")).toBe("/home");
    expect(swapStoreInPath("/anime/photos", "home")).toBe("/home/photos");
    expect(swapStoreInPath("/anime/photos/", "home")).toBe("/home/photos/");
  });

  it("keeps the query string out of the path", () => {
    expect(swapStoreInPath("/anime/photos?product=12", "kawaii")).toBe(
      "/kawaii/photos",
    );
  });

  it("lands on the same section's list from a detail route", () => {
    expect(swapStoreInPath("/anime/photos/12", "home")).toBe("/home/photos");
    expect(swapStoreInPath("/anime/photos/new", "home")).toBe("/home/photos");
    expect(swapStoreInPath("/anime/orders/42/", "home")).toBe("/home/orders");
  });
});

describe("isStoreDetailPath", () => {
  it("tells a detail route from a section list", () => {
    expect(isStoreDetailPath("/anime/photos/12")).toBe(true);
    expect(isStoreDetailPath("/anime/photos/new?product=12")).toBe(true);
    expect(isStoreDetailPath("/anime/photos")).toBe(false);
    expect(isStoreDetailPath("/anime")).toBe(false);
    expect(isStoreDetailPath("/sign-in")).toBe(false);
  });
});

describe("storeHref", () => {
  it("builds a store route", () => {
    expect(storeHref("anime", "")).toBe("/anime");
    expect(storeHref("anime", "photos")).toBe("/anime/photos");
  });
});

describe("isStoreSegment", () => {
  it("rejects console-owned segments", () => {
    expect(isStoreSegment("sign-in")).toBe(false);
    expect(isStoreSegment("api")).toBe(false);
    expect(isStoreSegment("_next")).toBe(false);
    expect(isStoreSegment("anime")).toBe(true);
  });
});
