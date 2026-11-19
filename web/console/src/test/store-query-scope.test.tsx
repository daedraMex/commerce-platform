import { QueryClient, useQuery, useQueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StoreQueryScope } from "@/components/providers/store-query-scope";
import {
  GlobalQueryClientProvider,
  useGlobalQueryClient,
} from "@/lib/query/global-query-client";

type Deferred = {
  promise: Promise<string>;
  resolve: (value: string) => void;
};

function deferred(): Deferred {
  let resolve = (_value: string) => {};
  const promise = new Promise<string>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

function Probe({
  store,
  fetchStore,
  clients,
}: {
  store: string;
  fetchStore: (store: string) => Promise<string>;
  clients: Set<QueryClient>;
}) {
  const client = useQueryClient();
  clients.add(client);
  const { data } = useQuery({
    queryKey: ["probe"],
    queryFn: () => fetchStore(store),
  });

  return <span data-testid="value">{data ?? "loading"}</span>;
}

function GlobalProbe({ clients }: { clients: Set<QueryClient> }) {
  const storeClient = useQueryClient();
  const globalClient = useGlobalQueryClient();
  clients.add(storeClient);
  clients.add(globalClient as QueryClient);

  return (
    <span data-testid="global">
      {globalClient === storeClient ? "same" : "different"}
    </span>
  );
}

describe("store query scope", () => {
  it("never shows store A's cached data inside store B", async () => {
    const clients = new Set<QueryClient>();
    const anime = deferred();
    const home = deferred();
    const fetchStore = vi.fn((store: string) =>
      store === "anime" ? anime.promise : home.promise,
    );

    const view = render(
      <StoreQueryScope store="anime">
        <Probe store="anime" fetchStore={fetchStore} clients={clients} />
      </StoreQueryScope>,
    );

    expect(screen.getByTestId("value")).toHaveTextContent("loading");
    anime.resolve("anime products");
    expect(await screen.findByText("anime products")).toBeInTheDocument();

    view.rerender(
      <StoreQueryScope store="home">
        <Probe store="home" fetchStore={fetchStore} clients={clients} />
      </StoreQueryScope>,
    );

    expect(screen.getByTestId("value")).toHaveTextContent("loading");
    expect(screen.queryByText("anime products")).not.toBeInTheDocument();

    home.resolve("home products");
    expect(await screen.findByText("home products")).toBeInTheDocument();
    expect(clients.size).toBeGreaterThan(1);
  });

  it("keeps global queries on the root client across store switches", () => {
    const clients = new Set<QueryClient>();
    const globalClient = new QueryClient();

    const view = render(
      <GlobalQueryClientProvider client={globalClient}>
        <StoreQueryScope store="anime">
          <GlobalProbe clients={clients} />
        </StoreQueryScope>
      </GlobalQueryClientProvider>,
    );

    expect(screen.getByTestId("global")).toHaveTextContent("different");

    view.rerender(
      <GlobalQueryClientProvider client={globalClient}>
        <StoreQueryScope store="home">
          <GlobalProbe clients={clients} />
        </StoreQueryScope>
      </GlobalQueryClientProvider>,
    );

    expect(screen.getByTestId("global")).toHaveTextContent("different");
    expect(clients).toContain(globalClient);
    expect(clients.size).toBe(3);
  });
});
