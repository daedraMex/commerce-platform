"use client";

import * as React from "react";

import {
  clearCurrentStore,
  setCurrentStore,
} from "@/lib/api/store-source";

const StoreRouteContext = React.createContext<string | null>(null);

export function StoreRoute({
  store,
  children,
}: {
  store: string;
  children: React.ReactNode;
}) {
  const bindStore = React.useCallback(
    (node: HTMLSpanElement | null) => {
      if (!node) {
        return undefined;
      }

      setCurrentStore(store);
      return () => clearCurrentStore(store);
    },
    [store],
  );

  return (
    <StoreRouteContext.Provider value={store}>
      <span hidden ref={bindStore} />
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
