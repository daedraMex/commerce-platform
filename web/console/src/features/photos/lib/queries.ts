import {
  getApiV1CatalogCategoriesListQueryKey,
  getApiV1StaffProductsListQueryKey,
  type ApiV1StaffProductsListParams,
} from "@commerce-platform/api-client";

export function photoCategoriesQueryKey(store: string) {
  return [...getApiV1CatalogCategoriesListQueryKey(), store] as const;
}

export function photoProductsQueryKey(
  store: string,
  params?: ApiV1StaffProductsListParams,
) {
  return [...getApiV1StaffProductsListQueryKey(params), store] as const;
}
