import axios, { type AxiosRequestConfig } from "axios";

export type ApiStoreResolver = (request: {
  signal: AbortSignal | undefined;
}) => string | undefined;

let storeResolver: ApiStoreResolver | undefined;

/**
 * Lets the host app tell the mutator which store owns a request. It runs
 * synchronously before axios builds its promise chain, so a late interceptor
 * cannot relabel the request after the route changed.
 */
export function setStoreResolver(resolver: ApiStoreResolver | undefined): void {
  storeResolver = resolver;
}

export const axiosInstance = axios.create({
  baseURL: "/api/backend",
  headers: {
    "X-Requested-With": "XMLHttpRequest",
  },
});

export const apiClient = <T>(
  config: AxiosRequestConfig,
  options?: AxiosRequestConfig,
): Promise<T> => {
  const signal = (options?.signal ?? config.signal) as AbortSignal | undefined;
  const store = storeResolver?.({ signal });

  return axiosInstance
    .request<T>({
      ...config,
      ...options,
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        ...(store ? { "X-Store": store } : {}),
        ...config.headers,
        ...options?.headers,
      },
    })
    .then((response) => response.data);
};
