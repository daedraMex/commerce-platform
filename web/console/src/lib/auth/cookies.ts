import type { NextRequest, NextResponse } from "next/server";

import type { TokenPairResponse } from "@commerce-platform/api-client";

import {
  ACCESS_COOKIE,
  ACCESS_MAX_AGE_SECONDS,
  REFRESH_COOKIE,
  REFRESH_MAX_AGE_SECONDS,
} from "./constants";

const baseCookieOptions = {
  httpOnly: true,
  secure: true,
  sameSite: "lax" as const,
  path: "/",
};

export function readAccessToken(request: NextRequest): string | undefined {
  return request.cookies.get(ACCESS_COOKIE)?.value;
}

export function readRefreshToken(request: NextRequest): string | undefined {
  return request.cookies.get(REFRESH_COOKIE)?.value;
}

export function setSessionCookies(
  response: NextResponse,
  tokens: TokenPairResponse,
): void {
  response.cookies.set(ACCESS_COOKIE, tokens.access, {
    ...baseCookieOptions,
    maxAge: ACCESS_MAX_AGE_SECONDS,
  });
  response.cookies.set(REFRESH_COOKIE, tokens.refresh, {
    ...baseCookieOptions,
    maxAge: REFRESH_MAX_AGE_SECONDS,
  });
}

export function clearSessionCookies(response: NextResponse): void {
  response.cookies.set(ACCESS_COOKIE, "", {
    ...baseCookieOptions,
    maxAge: 0,
    expires: new Date(0),
  });
  response.cookies.set(REFRESH_COOKIE, "", {
    ...baseCookieOptions,
    maxAge: 0,
    expires: new Date(0),
  });
}
