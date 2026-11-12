import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it } from "vitest";

import { POST as signIn } from "@/app/api/auth/sign-in/route";
import {
  NO_MEMBERSHIP_EMAIL,
  resetMockState,
  VALID_EMAIL,
  VALID_PASSWORD,
} from "@/mocks/handlers";

function signInRequest(body: Record<string, unknown>): NextRequest {
  return new NextRequest("http://localhost/api/auth/sign-in", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function setCookies(response: Response): string {
  return response.headers.getSetCookie().join("\n");
}

beforeEach(() => {
  resetMockState();
});

describe("POST /api/auth/sign-in", () => {
  it("stores the token pair in httpOnly Secure SameSite=Lax cookies", async () => {
    const response = await signIn(
      signInRequest({
        email: VALID_EMAIL,
        password: VALID_PASSWORD,
        next: "/anime",
      }),
    );

    expect(response.status).toBe(200);
    const body = await response.text();
    expect(JSON.parse(body)).toEqual({ redirectTo: "/anime" });

    const cookies = setCookies(response);
    expect(cookies).toContain("quetzal_access=access-1");
    expect(cookies).toContain("quetzal_refresh=refresh-1");
    expect(cookies.toLowerCase()).toContain("httponly");
    expect(cookies.toLowerCase()).toContain("secure");
    expect(cookies.toLowerCase()).toContain("samesite=lax");

    expect(body).not.toContain("access-1");
    expect(body).not.toContain("refresh-1");
  });

  it("redirects a form submission to the chosen store", async () => {
    const request = new NextRequest("http://localhost/api/auth/sign-in", {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        email: VALID_EMAIL,
        password: VALID_PASSWORD,
        next: "/anime",
      }).toString(),
    });

    const response = await signIn(request);

    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("http://localhost/anime");
    expect(setCookies(response)).toContain("quetzal_access=access-1");
  });

  it("rejects a user without an active membership and stores no session", async () => {
    const response = await signIn(
      signInRequest({
        email: NO_MEMBERSHIP_EMAIL,
        password: VALID_PASSWORD,
      }),
    );

    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({
      code: "no_active_membership",
    });
    expect(response.cookies.get("quetzal_access")?.value ?? "").toBe("");
    expect(response.cookies.get("quetzal_refresh")?.value ?? "").toBe("");
  });

  it("forwards the backend's invalid credentials problem", async () => {
    const response = await signIn(
      signInRequest({ email: VALID_EMAIL, password: "wrong" }),
    );

    expect(response.status).toBe(401);
    expect(response.headers.get("content-type")).toContain(
      "application/problem+json",
    );
    expect(await response.json()).toMatchObject({
      code: "invalid_credentials",
    });
    expect(setCookies(response)).toBe("");
  });

  it("validates the request shape before calling the backend", async () => {
    const response = await signIn(signInRequest({ email: "" }));

    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({
      code: "validation_error",
      errors: expect.arrayContaining([
        expect.objectContaining({ field: "email", code: "required" }),
        expect.objectContaining({ field: "password", code: "required" }),
      ]),
    });
  });
});
