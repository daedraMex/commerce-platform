import { NextRequest, NextResponse } from "next/server";

import { requestLogout } from "@/lib/auth/backend";
import {
  clearSessionCookies,
  readAccessToken,
  readRefreshToken,
} from "@/lib/auth/cookies";
import { CSRF_HEADER } from "@/lib/auth/constants";
import { problemResponse } from "@/lib/auth/problem";
import {
  forgetRefreshToken,
  refreshTokenPair,
} from "@/lib/auth/refresh";

async function blacklistRefreshToken(
  refreshToken: string,
  accessToken?: string,
): Promise<void> {
  if (accessToken) {
    const logout = await requestLogout(refreshToken, accessToken);
    if (logout.status !== 401) {
      return;
    }
  }

  const tokens = await refreshTokenPair(refreshToken);
  if (!tokens) {
    return;
  }

  await requestLogout(tokens.refresh, tokens.access);
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  if (!request.headers.get(CSRF_HEADER)) {
    return problemResponse(
      403,
      "csrf_header_missing",
      `The ${CSRF_HEADER} header is required.`,
    );
  }

  const refreshToken = readRefreshToken(request);
  const accessToken = readAccessToken(request);

  if (refreshToken) {
    await blacklistRefreshToken(refreshToken, accessToken).catch(
      () => undefined,
    );
    forgetRefreshToken(refreshToken);
  }

  const response = new NextResponse(null, { status: 204 });
  clearSessionCookies(response);
  return response;
}
