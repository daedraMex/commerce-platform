import axios, { type AxiosRequestConfig } from "axios";

export const axiosInstance = axios.create({
  baseURL: "/api/backend",
  headers: {
    "X-Requested-With": "XMLHttpRequest",
  },
});

export const apiClient = <T>(
  config: AxiosRequestConfig,
  options?: AxiosRequestConfig,
): Promise<T> =>
  axiosInstance
    .request<T>({
      ...config,
      ...options,
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        ...config.headers,
        ...options?.headers,
      },
    })
    .then((response) => response.data);
