import * as React from "react";

import { SessionGate } from "@/features/auth/organisms/session-gate";

export default async function StoreLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ store: string }>;
}) {
  const { store } = await params;

  return <SessionGate store={store}>{children}</SessionGate>;
}
