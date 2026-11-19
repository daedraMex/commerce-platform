import { axiosInstance } from "@commerce-platform/api-client";

import { getCurrentStore } from "@/lib/api/store-source";

let installed = false;

export function installStoreHeader(): void {
  if (installed) {
    return;
  }
  installed = true;

  axiosInstance.interceptors.request.use((config) => {
    if (typeof window === "undefined" || config.headers.has("X-Store")) {
      return config;
    }

    const store = getCurrentStore();
    if (store) {
      config.headers.set("X-Store", store);
    }

    return config;
  });
}
