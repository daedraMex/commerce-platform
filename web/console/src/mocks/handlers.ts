import { HttpResponse, http } from "msw";

import type { Me, TokenPairResponse } from "@commerce-platform/api-client";

export const VALID_EMAIL = "ana@example.com";
export const VALID_PASSWORD = "correct-horse";
export const REFRESH_EMAIL = "refresh@example.com";
export const NO_MEMBERSHIP_EMAIL = "nomembership@example.com";
export const LIMITED_EMAIL = "limited@example.com";

const MEMBERSHIPS: Me["memberships"] = [
  {
    store: { slug: "anime", name: "Anime", accent_color: "#4f46e5" },
    role: "store_admin",
    permissions: ["catalog.manage", "inventory.adjust"],
  },
  {
    store: { slug: "home", name: "Home", accent_color: "#0ea5e9" },
    role: "store_admin",
    permissions: ["catalog.manage", "inventory.adjust"],
  },
];

function membershipsFor(email: string): Me["memberships"] {
  if (email !== LIMITED_EMAIL) {
    return MEMBERSHIPS;
  }

  return MEMBERSHIPS.map((membership) => ({
    ...membership,
    role: "store_admin",
    permissions: ["inventory.adjust"],
  }));
}

type MockState = {
  email: string;
  accessToken: string;
  refreshToken: string;
  accessValid: boolean;
  accessVersion: number;
  refreshVersion: number;
  expireAfterValidation: boolean;
  memberships: Me["memberships"];
  refreshCalls: number;
};

function initialState(): MockState {
  return {
    email: VALID_EMAIL,
    accessToken: "access-1",
    refreshToken: "refresh-1",
    accessValid: false,
    accessVersion: 1,
    refreshVersion: 1,
    expireAfterValidation: false,
    memberships: MEMBERSHIPS,
    refreshCalls: 0,
  };
}

let state = initialState();

export function resetMockState(): void {
  state = initialState();
}

export function currentMockState(): Readonly<MockState> {
  return state;
}

function problem(status: number, code: string, detail: string) {
  return HttpResponse.json(
    {
      type: "about:blank",
      title: status === 401 ? "Unauthorized" : "Bad Request",
      status,
      detail,
      code,
    },
    {
      status,
      headers: { "content-type": "application/problem+json" },
    },
  );
}

function tokenPair(): TokenPairResponse {
  return {
    access: `access-${state.accessVersion}`,
    refresh: `refresh-${state.refreshVersion}`,
  };
}

function meBody(): Me {
  return {
    user: { id: 1, email: state.email },
    memberships: state.memberships,
  };
}

function authorized(request: Request): boolean {
  return (
    state.accessValid &&
    request.headers.get("authorization") === `Bearer ${state.accessToken}`
  );
}

export const handlers = [
  http.post("*/api/v1/auth/token/", async ({ request }) => {
    const body = (await request.json()) as {
      email?: string;
      password?: string;
    };
    const email = body.email ?? "";
    const knownEmail =
      email === VALID_EMAIL ||
      email === REFRESH_EMAIL ||
      email === NO_MEMBERSHIP_EMAIL ||
      email === LIMITED_EMAIL;

    if (!knownEmail || body.password !== VALID_PASSWORD) {
      return problem(401, "invalid_credentials", "Invalid email or password.");
    }

    state = {
      ...initialState(),
      email,
      accessValid: true,
      expireAfterValidation: email === REFRESH_EMAIL,
      memberships:
        email === NO_MEMBERSHIP_EMAIL ? [] : membershipsFor(email),
    };

    return HttpResponse.json(tokenPair());
  }),

  http.post("*/api/v1/auth/token/refresh/", async ({ request }) => {
    const body = (await request.json()) as { refresh?: string };
    state.refreshCalls += 1;

    if (body.refresh !== state.refreshToken) {
      return problem(401, "token_invalid", "Token is invalid");
    }

    state.accessVersion += 1;
    state.refreshVersion += 1;
    state.accessToken = `access-${state.accessVersion}`;
    state.refreshToken = `refresh-${state.refreshVersion}`;
    state.accessValid = true;

    return HttpResponse.json(tokenPair());
  }),

  http.post("*/api/v1/auth/logout/", async ({ request }) => {
    const body = (await request.json()) as { refresh?: string };

    if (body.refresh !== state.refreshToken) {
      return problem(401, "token_invalid", "Token is invalid");
    }

    state.accessValid = false;
    state.refreshToken = "";

    return new HttpResponse(null, { status: 204 });
  }),

  http.get("*/api/v1/me/", ({ request }) => {
    if (!authorized(request)) {
      return problem(
        401,
        "token_invalid",
        "Given token not valid for any token type",
      );
    }

    const body = meBody();

    if (state.expireAfterValidation) {
      state.expireAfterValidation = false;
      state.accessValid = false;
    }

    return HttpResponse.json(body);
  }),
];
