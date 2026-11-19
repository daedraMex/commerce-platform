"use client";

import * as React from "react";

import { setCurrentStore } from "@/lib/api/store-source";

const StoreRouteContext = React.createContext<string | null>(null);

export function StoreRoute({
  store,
  children,
}: {
  store: string;
  children: React.ReactNode;
}) {
  setCurrentStore(store);

  return (
    <StoreRouteContext.Provider value={store}>
      {children}
    </StoreRouteContext.Provider>
  );
}

export function useStoreRoute(): string {
  const store = React.useContext(StoreRouteContext);
  if (!store) {
    throw new Error("useStoreRoute must be used inside StoreRoute");
  }
  return store;
}
