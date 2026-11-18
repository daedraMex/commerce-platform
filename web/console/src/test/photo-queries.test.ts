import { describe, expect, it } from "vitest";

import {
  photoCategoriesQueryKey,
  photoProductsQueryKey,
} from "@/features/photos/lib/queries";

describe("photo query keys", () => {
  it("scopes the catalog queries to the store so cached data cannot leak", () => {
    expect(photoCategoriesQueryKey("anime")).not.toEqual(
      photoCategoriesQueryKey("kawaii"),
    );
    expect(photoProductsQueryKey("anime", { page_size: 100 })).not.toEqual(
      photoProductsQueryKey("kawaii", { page_size: 100 }),
    );

    expect(photoProductsQueryKey("anime", { page_size: 100 })).toContain(
      "anime",
    );
    expect(photoProductsQueryKey("anime", { page_size: 100 })).not.toContain(
      "kawaii",
    );
  });

  it("keeps the same key for the same store and filters", () => {
    expect(photoCategoriesQueryKey("anime")).toEqual(
      photoCategoriesQueryKey("anime"),
    );
    expect(photoProductsQueryKey("anime", { page_size: 100 })).toEqual(
      photoProductsQueryKey("anime", { page_size: 100 }),
    );
  });
});
