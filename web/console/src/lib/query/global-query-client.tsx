"use client";

import type { QueryClient } from "@tanstack/react-query";
import * as React from "react";

const GlobalQueryClientContext = React.createContext<QueryClient | null>(null);

export function GlobalQueryClientProvider({
  client,
  children,
}: {
  client: QueryClient;
  children: React.ReactNode;
}) {
  return (
    <GlobalQueryClientContext.Provider value={client}>
      {children}
    </GlobalQueryClientContext.Provider>
  );
}

export function useGlobalQueryClient(): QueryClient | null {
  return React.useContext(GlobalQueryClientContext);
}
