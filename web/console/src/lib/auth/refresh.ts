import type { TokenPairResponse } from "@commerce-platform/api-client";

import { requestRefresh } from "./backend";

// Single-flight and short-lived cache for refreshed token pairs.
//
// Refresh tokens rotate and the used one is blacklisted, so two concurrent
// requests that both carry the same refresh token must not both call the
// backend: the second refresh would either be rejected (signing the user out)
// or mint a second valid pair. Callers with the same token share one refresh,
// and the resolved pair is reused for a short window so a request still
// carrying the old token right after the rotation does not refresh again.
//
// This state is per server process. Multiple console instances each keep their
// own cache; correctness still holds because every refresh response carries the
// same new pair back to the browser.
const REFRESH_CACHE_TTL_MS = 30_000;

type CachedPair = {
  tokens: TokenPairResponse;
  expiresAt: number;
};

const cache = new Map<string, CachedPair>();
const inFlight = new Map<string, Promise<TokenPairResponse | null>>();

export async function refreshTokenPair(
  refreshToken: string,
): Promise<TokenPairResponse | null> {
  const cached = cache.get(refreshToken);
  if (cached && cached.expiresAt > Date.now()) {
    return cached.tokens;
  }

  const pending = inFlight.get(refreshToken);
  if (pending) {
    return pending;
  }

  const request = (async (): Promise<TokenPairResponse | null> => {
    const response = await requestRefresh(refreshToken);
    if (!response.ok) {
      return null;
    }

    const tokens = (await response.json()) as TokenPairResponse;
    const expiresAt = Date.now() + REFRESH_CACHE_TTL_MS;
    cache.set(refreshToken, { tokens, expiresAt });
    cache.set(tokens.refresh, { tokens, expiresAt });
    return tokens;
  })();

  inFlight.set(refreshToken, request);
  try {
    return await request;
  } finally {
    inFlight.delete(refreshToken);
  }
}

export function forgetRefreshToken(refreshToken: string): void {
  cache.delete(refreshToken);
  for (const [key, entry] of cache) {
    if (entry.tokens.refresh === refreshToken) {
      cache.delete(key);
    }
  }
}

export function resetRefreshCache(): void {
  cache.clear();
  inFlight.clear();
}
