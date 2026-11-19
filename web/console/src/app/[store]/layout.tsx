import * as React from "react";

import { StoreQueryScope } from "@/components/providers/store-query-scope";
import { StoreRoute } from "@/components/providers/store-route";
import { SessionGate } from "@/features/auth/organisms/session-gate";

export default async function StoreLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ store: string }>;
}) {
  const { store } = await params;

  return (
    <StoreRoute store={store}>
      <SessionGate store={store}>
        <StoreQueryScope store={store}>{children}</StoreQueryScope>
      </SessionGate>
    </StoreRoute>
  );
}
