import { NextRequest, type NextResponse } from "next/server";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { POST as signIn } from "@/app/api/auth/sign-in/route";
import { POST as signOut } from "@/app/api/auth/sign-out/route";
import {
  resetMockState,
  VALID_EMAIL,
  VALID_PASSWORD,
} from "@/mocks/handlers";
import { server } from "@/mocks/server";

function cookieHeader(response: NextResponse): string {
  const access = response.cookies.get("quetzal_access")?.value;
  const refresh = response.cookies.get("quetzal_refresh")?.value;
  return `quetzal_access=${access}; quetzal_refresh=${refresh}`;
}

async function signedInSession(): Promise<NextResponse> {
  return signIn(
    new NextRequest("http://localhost/api/auth/sign-in", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email: VALID_EMAIL, password: VALID_PASSWORD }),
    }),
  );
}

function signOutRequest(cookie?: string): NextRequest {
  return new NextRequest("http://localhost/api/auth/sign-out", {
    method: "POST",
    headers: cookie ? { cookie } : undefined,
  });
}

beforeEach(() => {
  resetMockState();
});

describe("POST /api/auth/sign-out", () => {
  it("blacklists the refresh token and clears both cookies", async () => {
    const session = await signedInSession();
    let sentRefresh: string | undefined;
    server.use(
      http.post("*/api/v1/auth/logout/", async ({ request }) => {
        const body = (await request.json()) as { refresh: string };
        sentRefresh = body.refresh;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    const response = await signOut(signOutRequest(cookieHeader(session)));

    expect(response.status).toBe(204);
    expect(sentRefresh).toBe("refresh-1");
    const cookies = response.headers.getSetCookie().join("\n");
    expect(cookies).toContain("quetzal_access=");
    expect(cookies).toContain("quetzal_refresh=");
    expect(cookies).toContain("Max-Age=0");
    expect(cookies.toLowerCase()).toContain("httponly");
  });

  it("still clears the cookies when the backend fails", async () => {
    const session = await signedInSession();
    server.use(
      http.post("*/api/v1/auth/logout/", () =>
        HttpResponse.json(
          { code: "internal_error" },
          { status: 500 },
        ),
      ),
      http.post("*/api/v1/auth/token/refresh/", () =>
        HttpResponse.json({ code: "token_invalid" }, { status: 401 }),
      ),
    );

    const response = await signOut(signOutRequest(cookieHeader(session)));

    expect(response.status).toBe(204);
    expect(
      response.headers.getSetCookie().join("\n"),
    ).toContain("Max-Age=0");
  });

  it("clears cookies even with no session", async () => {
    const response = await signOut(signOutRequest());

    expect(response.status).toBe(204);
    expect(
      response.headers.getSetCookie().join("\n"),
    ).toContain("Max-Age=0");
  });
});
