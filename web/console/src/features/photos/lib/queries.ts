import {
  getApiV1CatalogCategoriesListQueryKey,
  getApiV1StaffPhotosRetrieveQueryKey,
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

/** One polling run of a submission: a new processing attempt starts a fresh backoff. */
export function photoSubmissionQueryKey(
  store: string,
  submissionId: number,
  attempt: number,
) {
  return [...getApiV1StaffPhotosRetrieveQueryKey(submissionId), store, attempt] as const;
}
