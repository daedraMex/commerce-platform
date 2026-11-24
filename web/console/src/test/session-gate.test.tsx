import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Me } from "@commerce-platform/api-client";

import { ThemeProvider } from "@/components/providers/theme-provider";
import { SessionGate } from "@/features/auth/organisms/session-gate";
import messages from "../../messages/es.json";

const navigation = vi.hoisted(() => ({
  redirect: vi.fn(),
  push: vi.fn(),
  refresh: vi.fn(),
  replace: vi.fn(),
}));

const session = vi.hoisted(() => ({ current: vi.fn() }));

vi.mock("next/navigation", () => ({
  redirect: navigation.redirect,
  usePathname: () => "/anime",
  useRouter: () => ({
    push: navigation.push,
    refresh: navigation.refresh,
    replace: navigation.replace,
  }),
}));

vi.mock("@commerce-platform/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@commerce-platform/api-client")>()),
  useApiV1MeRetrieve: () => session.current(),
}));

const memberships: Me["memberships"] = [
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

const signedIn: Me = {
  user: { id: 1, email: "ana@example.com" },
  memberships,
};

function queryResult(
  result: Partial<ReturnType<typeof session.current>> = {},
) {
  return {
    data: undefined,
    error: undefined,
    isPending: false,
    ...result,
  };
}

function gate(store: string) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      <ThemeProvider>
        <NextIntlClientProvider locale="es" messages={messages}>
          <SessionGate store={store}>
            <span>content</span>
          </SessionGate>
        </NextIntlClientProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("SessionGate", () => {
  it("redirects an unauthorized session to sign in during render", () => {
    session.current.mockReturnValue(
      queryResult({ error: { response: { status: 401 } } }),
    );

    render(gate("anime"));

    expect(navigation.redirect).toHaveBeenCalledWith(
      "/sign-in?next=%2Fanime",
    );
    expect(navigation.replace).not.toHaveBeenCalled();
    expect(screen.queryByText("content")).not.toBeInTheDocument();
  });

  it("redirects a store the user cannot open to their first store during render", () => {
    session.current.mockReturnValue(queryResult({ data: signedIn }));

    render(gate("kawaii"));

    expect(navigation.redirect).toHaveBeenCalledWith("/anime");
    expect(navigation.replace).not.toHaveBeenCalled();
    expect(screen.queryByText("content")).not.toBeInTheDocument();
  });

  it("does not redirect an unauthorized session while sign out is in flight", async () => {
    let finishSignOut = (_response: Response) => {};
    const fetchMock = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          finishSignOut = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    session.current.mockReturnValue(queryResult({ data: signedIn }));

    const view = render(gate("anime"));
    fireEvent.click(screen.getByRole("button", { name: "Salir" }));

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/sign-out",
      expect.objectContaining({ method: "POST" }),
    );

    session.current.mockReturnValue(
      queryResult({ error: { response: { status: 401 } } }),
    );
    view.rerender(gate("anime"));

    expect(navigation.redirect).not.toHaveBeenCalled();

    await act(async () => {
      finishSignOut(new Response(null, { status: 204 }));
    });

    expect(navigation.replace).toHaveBeenCalledWith("/sign-in");
    expect(navigation.refresh).toHaveBeenCalled();
    expect(navigation.redirect).not.toHaveBeenCalled();
  });
});
