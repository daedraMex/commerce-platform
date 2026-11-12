import { NextRequest, NextResponse } from "next/server";

import type { Me, TokenPairResponse } from "@commerce-platform/api-client";

import { requestMe, requestTokenPair } from "@/lib/auth/backend";
import { clearSessionCookies, setSessionCookies } from "@/lib/auth/cookies";
import { forwardProblem, problemResponse } from "@/lib/auth/problem";

type SignInPayload = {
  email?: unknown;
  password?: unknown;
  store?: unknown;
  next?: unknown;
};

async function readPayload(request: NextRequest): Promise<SignInPayload | null> {
  const contentType = request.headers.get("content-type") ?? "";

  try {
    if (contentType.includes("application/json")) {
      return (await request.json()) as SignInPayload;
    }
    if (
      contentType.includes("application/x-www-form-urlencoded") ||
      contentType.includes("multipart/form-data")
    ) {
      return Object.fromEntries(await request.formData());
    }
  } catch {
    return null;
  }

  return null;
}

function requestedStore(payload: SignInPayload): string | undefined {
  if (typeof payload.store === "string" && payload.store.length > 0) {
    return payload.store;
  }
  if (typeof payload.next === "string" && payload.next.startsWith("/")) {
    const [first] = payload.next.split("?")[0].split("/").filter(Boolean);
    if (first && first !== "sign-in" && first !== "api") {
      return first;
    }
  }
  return undefined;
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const contentType = request.headers.get("content-type") ?? "";
  const wantsRedirect =
    contentType.includes("application/x-www-form-urlencoded") ||
    contentType.includes("multipart/form-data") ||
    (request.headers.get("accept") ?? "").includes("text/html");
  const payload = await readPayload(request);

  if (!payload) {
    return problemResponse(
      400,
      "validation_error",
      "Validation failed.",
      [{ field: "non_field_errors", code: "invalid", detail: "Invalid request body." }],
    );
  }

  const email = typeof payload.email === "string" ? payload.email.trim() : "";
  const password = typeof payload.password === "string" ? payload.password : "";
  const missing = [
    ...(email ? [] : ["email"]),
    ...(password ? [] : ["password"]),
  ];

  if (missing.length > 0) {
    return problemResponse(
      400,
      "validation_error",
      "Validation failed.",
      missing.map((field) => ({
        field,
        code: "required",
        detail: "This field is required.",
      })),
    );
  }

  const tokenResponse = await requestTokenPair(email, password);
  if (!tokenResponse.ok) {
    return forwardProblem(tokenResponse);
  }

  const tokens = (await tokenResponse.json()) as TokenPairResponse;
  const meResponse = await requestMe(tokens.access);
  if (!meResponse.ok) {
    return forwardProblem(meResponse);
  }

  const me = (await meResponse.json()) as Me;
  const memberships = me.memberships ?? [];

  if (memberships.length === 0) {
    const response = problemResponse(
      403,
      "no_active_membership",
      "You have no active store membership.",
    );
    clearSessionCookies(response);
    return response;
  }

  const wanted = requestedStore(payload);
  const membership =
    memberships.find((candidate) => candidate.store.slug === wanted) ??
    memberships[0];

  const destination = new URL(`/${membership.store.slug}`, request.url);
  const response = wantsRedirect
    ? NextResponse.redirect(destination, 303)
    : NextResponse.json({ redirectTo: destination.pathname });
  setSessionCookies(response, tokens);
  return response;
}
