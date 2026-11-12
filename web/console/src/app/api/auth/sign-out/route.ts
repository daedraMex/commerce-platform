import { NextRequest, NextResponse } from "next/server";

import type { TokenPairResponse } from "@commerce-platform/api-client";

import {
  requestLogout,
  requestRefresh,
} from "@/lib/auth/backend";
import {
  clearSessionCookies,
  readAccessToken,
  readRefreshToken,
} from "@/lib/auth/cookies";

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

  const refreshed = await requestRefresh(refreshToken);
  if (!refreshed.ok) {
    return;
  }

  const tokens = (await refreshed.json()) as TokenPairResponse;
  await requestLogout(tokens.refresh, tokens.access);
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const refreshToken = readRefreshToken(request);
  const accessToken = readAccessToken(request);

  if (refreshToken) {
    await blacklistRefreshToken(refreshToken, accessToken).catch(
      () => undefined,
    );
  }

  const response = new NextResponse(null, { status: 204 });
  clearSessionCookies(response);
  return response;
}
