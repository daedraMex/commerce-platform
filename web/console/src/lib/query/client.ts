import {
  QueryClient,
  type DefaultError,
  type DefaultedQueryObserverOptions,
  type QueryClientConfig,
  type QueryKey,
  type QueryObserverOptions,
} from "@tanstack/react-query";

import { bindStoreToSignal } from "@/lib/api/store-source";

/**
 * Records the store that owns every query on the signal React Query passes to
 * its query function, so the request keeps that store even if the route (and
 * its fallback store) changes before axios sends it.
 */
class StoreQueryClient extends QueryClient {
  private readonly store: string;

  constructor(store: string, config: QueryClientConfig) {
    super(config);
    this.store = store;
  }

  override defaultQueryOptions<
    TQueryFnData = unknown,
    TError = DefaultError,
    TData = TQueryFnData,
    TQueryData = TQueryFnData,
    TQueryKey extends QueryKey = QueryKey,
    TPageParam = never,
  >(
    options:
      | QueryObserverOptions<
          TQueryFnData,
          TError,
          TData,
          TQueryData,
          TQueryKey,
          TPageParam
        >
      | DefaultedQueryObserverOptions<
          TQueryFnData,
          TError,
          TData,
          TQueryData,
          TQueryKey
        >,
  ): DefaultedQueryObserverOptions<
    TQueryFnData,
    TError,
    TData,
    TQueryData,
    TQueryKey
  > {
    const defaulted = super.defaultQueryOptions(options);
    const queryFn = defaulted.queryFn;
    if (typeof queryFn !== "function") {
      return defaulted;
    }

    return {
      ...defaulted,
      queryFn: ((context) => {
        bindStoreToSignal(context.signal, this.store);
        return queryFn(context);
      }) as typeof queryFn,
    };
  }
}

export function createQueryClient(store?: string): QueryClient {
  const config: QueryClientConfig = {
    defaultOptions: {
      queries: {
        retry: false,
        refetchOnWindowFocus: false,
      },
    },
  };

  return store ? new StoreQueryClient(store, config) : new QueryClient(config);
}
