import { NextRequest, NextResponse } from "next/server";

import type { TokenPairResponse } from "@commerce-platform/api-client";

import { apiBaseUrl } from "@/lib/auth/backend";
import {
  clearSessionCookies,
  readAccessToken,
  readRefreshToken,
  setSessionCookies,
} from "@/lib/auth/cookies";
import { CSRF_HEADER } from "@/lib/auth/constants";
import { problemResponse } from "@/lib/auth/problem";
import { refreshTokenPair } from "@/lib/auth/refresh";

export const dynamic = "force-dynamic";

const SKIPPED_REQUEST_HEADERS = new Set([
  "authorization",
  "connection",
  "content-length",
  "cookie",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

const SKIPPED_RESPONSE_HEADERS = new Set([
  "connection",
  "content-encoding",
  "content-length",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "set-cookie",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

function backendPath(request: NextRequest): string {
  const stripped = request.nextUrl.pathname.replace(/^\/api\/backend/, "");
  if (stripped.length === 0) {
    return "/";
  }
  return stripped.endsWith("/") ? stripped : `${stripped}/`;
}

function targetUrl(request: NextRequest): string {
  return `${apiBaseUrl()}${backendPath(request)}${request.nextUrl.search}`;
}

function forwardHeaders(request: NextRequest, accessToken?: string): Headers {
  const headers = new Headers();
  request.headers.forEach((value, name) => {
    if (SKIPPED_REQUEST_HEADERS.has(name.toLowerCase())) {
      return;
    }
    headers.set(name, value);
  });
  if (accessToken) {
    headers.set("authorization", `Bearer ${accessToken}`);
  }
  return headers;
}

async function callBackend(
  request: NextRequest,
  body: ArrayBuffer | undefined,
  accessToken?: string,
): Promise<Response> {
  return fetch(targetUrl(request), {
    method: request.method.toUpperCase(),
    headers: forwardHeaders(request, accessToken),
    body: body && body.byteLength > 0 ? body : undefined,
    redirect: "manual",
    cache: "no-store",
  });
}

async function toNextResponse(upstream: Response): Promise<NextResponse> {
  const headers = new Headers();
  upstream.headers.forEach((value, name) => {
    if (SKIPPED_RESPONSE_HEADERS.has(name.toLowerCase())) {
      return;
    }
    headers.set(name, value);
  });

  const withoutBody = [204, 205, 304].includes(upstream.status);
  const body = withoutBody ? null : await upstream.arrayBuffer();

  return new NextResponse(body, { status: upstream.status, headers });
}

async function proxy(request: NextRequest): Promise<NextResponse> {
  if (!request.headers.get(CSRF_HEADER)) {
    return problemResponse(
      403,
      "csrf_header_missing",
      `The ${CSRF_HEADER} header is required.`,
    );
  }

  const path = backendPath(request);
  if (path.startsWith("/api/v1/auth/")) {
    return problemResponse(
      404,
      "not_found",
      "Auth endpoints are handled by the console server.",
    );
  }

  const accessToken = readAccessToken(request);
  const refreshToken = readRefreshToken(request);
  const method = request.method.toUpperCase();
  const requestBody =
    method === "GET" || method === "HEAD"
      ? undefined
      : await request.arrayBuffer();

  let upstream = await callBackend(request, requestBody, accessToken);
  let rotated: TokenPairResponse | undefined;

  if (upstream.status === 401 && refreshToken) {
    rotated = (await refreshTokenPair(refreshToken)) ?? undefined;
    if (!rotated) {
      const response = await toNextResponse(upstream);
      clearSessionCookies(response);
      return response;
    }

    upstream = await callBackend(request, requestBody, rotated.access);

    if (upstream.status === 401) {
      const response = await toNextResponse(upstream);
      clearSessionCookies(response);
      return response;
    }
  }

  const response = await toNextResponse(upstream);

  if (rotated) {
    setSessionCookies(response, rotated);
  } else if (upstream.status === 401) {
    clearSessionCookies(response);
  }

  return response;
}

export function GET(request: NextRequest): Promise<NextResponse> {
  return proxy(request);
}

export function POST(request: NextRequest): Promise<NextResponse> {
  return proxy(request);
}

export function PUT(request: NextRequest): Promise<NextResponse> {
  return proxy(request);
}

export function PATCH(request: NextRequest): Promise<NextResponse> {
  return proxy(request);
}

export function DELETE(request: NextRequest): Promise<NextResponse> {
  return proxy(request);
}
