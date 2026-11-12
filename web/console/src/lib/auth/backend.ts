const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

export function apiBaseUrl(): string {
  return (process.env.API_BASE_URL ?? DEFAULT_API_BASE_URL).replace(/\/$/, "");
}

function backendUrl(path: string): string {
  return `${apiBaseUrl()}${path}`;
}

function jsonHeaders(accessToken?: string): HeadersInit {
  return {
    "content-type": "application/json",
    accept: "application/json",
    ...(accessToken ? { authorization: `Bearer ${accessToken}` } : {}),
  };
}

export function requestTokenPair(
  email: string,
  password: string,
): Promise<Response> {
  return fetch(backendUrl("/api/v1/auth/token/"), {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ email, password }),
    cache: "no-store",
  });
}

export function requestRefresh(refreshToken: string): Promise<Response> {
  return fetch(backendUrl("/api/v1/auth/token/refresh/"), {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ refresh: refreshToken }),
    cache: "no-store",
  });
}

export function requestMe(accessToken: string): Promise<Response> {
  return fetch(backendUrl("/api/v1/me/"), {
    method: "GET",
    headers: jsonHeaders(accessToken),
    cache: "no-store",
  });
}

export function requestLogout(
  refreshToken: string,
  accessToken: string,
): Promise<Response> {
  return fetch(backendUrl("/api/v1/auth/logout/"), {
    method: "POST",
    headers: jsonHeaders(accessToken),
    body: JSON.stringify({ refresh: refreshToken }),
    cache: "no-store",
  });
}
