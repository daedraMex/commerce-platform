"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import * as React from "react";

import { createQueryClient } from "@/lib/query/client";

function StoreQueryCache({
  store,
  children,
}: {
  store: string;
  children: React.ReactNode;
}) {
  const [queryClient] = React.useState(() => createQueryClient(store));

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

export function StoreQueryScope({
  store,
  children,
}: {
  store: string;
  children: React.ReactNode;
}) {
  return (
    <StoreQueryCache key={store} store={store}>
      {children}
    </StoreQueryCache>
  );
}
