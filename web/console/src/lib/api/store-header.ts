import {
  axiosInstance,
  setStoreResolver,
} from "@commerce-platform/api-client";

import {
  getCurrentStore,
  getStoreFromSignal,
} from "@/lib/api/store-source";

let installed = false;

function storeForRequest(signal: AbortSignal | undefined): string | undefined {
  // A signal comes from a query client and must only use that client's store.
  // Direct calls (uploads, mutations) have no signal and use the committed route.
  return signal ? getStoreFromSignal(signal) : getCurrentStore();
}

export function installStoreHeader(): void {
  if (installed) {
    return;
  }
  installed = true;

  setStoreResolver(({ signal }) => storeForRequest(signal));

  axiosInstance.interceptors.request.use((config) => {
    if (typeof window === "undefined" || config.headers.has("X-Store")) {
      return config;
    }

    const store = storeForRequest(config.signal as AbortSignal | undefined);
    if (store) {
      config.headers.set("X-Store", store);
    }

    return config;
  });
}
