import { NextRequest, type NextResponse } from "next/server";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { GET as proxyGet } from "@/app/api/backend/[...path]/route";
import { POST as signIn } from "@/app/api/auth/sign-in/route";
import {
  CSRF_HEADER,
  CSRF_HEADER_VALUE,
} from "@/lib/auth/constants";
import {
  REFRESH_EMAIL,
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

function proxyRequest(
  path = "/api/backend/api/v1/me/",
  options: { cookie?: string; headers?: Record<string, string> } = {},
): NextRequest {
  const headers: Record<string, string> = {
    [CSRF_HEADER]: CSRF_HEADER_VALUE,
    ...options.headers,
  };
  if (options.cookie) {
    headers.cookie = options.cookie;
  }
  return new NextRequest(`http://localhost${path}`, { headers });
}

async function signInAs(email: string): Promise<NextResponse> {
  return signIn(
    new NextRequest("http://localhost/api/auth/sign-in", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, password: VALID_PASSWORD, next: "/anime" }),
    }),
  );
}

beforeEach(() => {
  resetMockState();
});

describe("GET /api/backend/[...path]", () => {
  it("refuses requests without the custom CSRF header", async () => {
    const response = await proxyGet(
      new NextRequest("http://localhost/api/backend/api/v1/me/"),
    );

    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({
      code: "csrf_header_missing",
    });
  });

  it("attaches the access token, forwards X-Store and hides the browser cookies", async () => {
    let seen: Request | undefined;
    server.use(
      http.get("*/api/v1/me/", ({ request }) => {
        seen = request;
        return HttpResponse.json({
          user: { id: 1, email: VALID_EMAIL },
          memberships: [],
        });
      }),
    );

    const response = await proxyGet(
      proxyRequest("/api/backend/api/v1/me/", {
        cookie: "quetzal_access=access-1; quetzal_refresh=refresh-1",
        headers: { "x-store": "anime" },
      }),
    );

    expect(response.status).toBe(200);
    expect(seen?.headers.get("authorization")).toBe("Bearer access-1");
    expect(seen?.headers.get("x-store")).toBe("anime");
    expect(seen?.headers.get("cookie")).toBeNull();
    expect(
      response.headers.get("set-cookie"),
    ).toBeNull();
  });

  it("rotates an expired access token and retries the request", async () => {
    const session = await signInAs(REFRESH_EMAIL);
    const response = await proxyGet(proxyRequest(undefined, {
      cookie: cookieHeader(session),
    }));

    expect(response.status).toBe(200);
    expect(response.cookies.get("quetzal_access")?.value).toBe("access-2");
    expect(response.cookies.get("quetzal_refresh")?.value).toBe("refresh-2");

    const cookies = response.headers.getSetCookie().join("\n");
    expect(cookies).toContain("quetzal_access=access-2");
    expect(cookies).toContain("quetzal_refresh=refresh-2");
    expect(cookies.toLowerCase()).toContain("httponly");
    expect(cookies.toLowerCase()).toContain("samesite=lax");

    const body = (await response.json()) as { memberships: unknown[] };
    expect(body.memberships).toHaveLength(2);
  });

  it("replays the request body after refreshing", async () => {
    const session = await signInAs(REFRESH_EMAIL);
    const bodies: string[] = [];
    server.use(
      http.post("*/api/v1/test/", async ({ request }) => {
        bodies.push(await request.text());
        if (request.headers.get("authorization") === "Bearer access-1") {
          return HttpResponse.json(
            { code: "token_invalid" },
            { status: 401 },
          );
        }
        return HttpResponse.json({ ok: true });
      }),
    );

    const response = await proxyGet(
      new NextRequest("http://localhost/api/backend/api/v1/test/", {
        method: "POST",
        headers: {
          [CSRF_HEADER]: CSRF_HEADER_VALUE,
          "content-type": "application/json",
          cookie: cookieHeader(session),
        },
        body: JSON.stringify({ name: "Frazada" }),
      }),
    );

    expect(response.status).toBe(200);
    expect(bodies).toEqual(['{"name":"Frazada"}', '{"name":"Frazada"}']);
    expect(response.cookies.get("quetzal_access")?.value).toBe("access-2");
  });

  it("clears the session when the refresh token is no longer valid", async () => {
    const response = await proxyGet(
      proxyRequest(undefined, {
        cookie: "quetzal_access=access-1; quetzal_refresh=stale",
      }),
    );

    expect(response.status).toBe(401);
    const cookies = response.headers.getSetCookie().join("\n");
    expect(cookies).toContain("quetzal_access=");
    expect(cookies).toContain("quetzal_refresh=");
    expect(cookies).toContain("Max-Age=0");
  });

  it("does not refresh a failed sign-in through the proxy", async () => {
    let refreshCalled = false;
    server.use(
      http.get("*/api/v1/auth/token/", () =>
        HttpResponse.json(
          { code: "invalid_credentials" },
          { status: 401 },
        ),
      ),
      http.post("*/api/v1/auth/token/refresh/", () => {
        refreshCalled = true;
        return HttpResponse.json(
          { access: "access-2", refresh: "refresh-2" },
          { status: 200 },
        );
      }),
    );

    const response = await proxyGet(
      proxyRequest("/api/backend/api/v1/auth/token/", {
        cookie: "quetzal_refresh=refresh-1",
      }),
    );

    expect(response.status).toBe(401);
    expect(refreshCalled).toBe(false);
  });
});
