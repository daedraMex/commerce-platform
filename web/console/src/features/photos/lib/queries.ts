import {
  getApiV1CatalogCategoriesListQueryKey,
  getApiV1StaffPhotosRetrieveQueryKey,
  getApiV1StaffProductsImagesRetrieveQueryKey,
  getApiV1StaffProductsListQueryKey,
  getApiV1StaffProductsRetrieveQueryKey,
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

export function photoProductQueryKey(store: string, productId: number) {
  return [...getApiV1StaffProductsRetrieveQueryKey(productId), store] as const;
}

/** One polling run of a submission: a new processing attempt starts a fresh backoff. */
export function photoSubmissionQueryKey(
  store: string,
  submissionId: number,
  attempt: number,
) {
  return [...getApiV1StaffPhotosRetrieveQueryKey(submissionId), store, attempt] as const;
}

export function photoCarouselQueryKey(store: string, productId: number) {
  return [
    ...getApiV1StaffProductsImagesRetrieveQueryKey(productId),
    store,
  ] as const;
}
