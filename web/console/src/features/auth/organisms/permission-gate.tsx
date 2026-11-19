"use client";

import * as React from "react";
import { useTranslations } from "next-intl";

import { useApiV1MeRetrieve } from "@commerce-platform/api-client";

import { useGlobalQueryClient } from "@/lib/query/global-query-client";
import { SESSION_STALE_TIME_MS } from "../lib/session-query";

type PermissionGateProps = {
  store: string;
  permission: string;
  children: React.ReactNode;
};

export function PermissionGate({
  store,
  permission,
  children,
}: PermissionGateProps) {
  const t = useTranslations("Session");
  const globalQueryClient = useGlobalQueryClient();
  const { data, isPending } = useApiV1MeRetrieve(
    {
      query: {
        retry: false,
        staleTime: SESSION_STALE_TIME_MS,
      },
    },
    globalQueryClient ?? undefined,
  );

  const membership = data?.memberships.find(
    (item) => item.store.slug === store,
  );

  if (isPending) {
    return (
      <main className="mx-auto flex min-h-[60dvh] max-w-md items-center justify-center p-6 text-sm">
        {t("loading")}
      </main>
    );
  }

  if (!data) {
    return null;
  }

  if (!membership?.permissions.includes(permission)) {
    return (
      <main
        data-store={store}
        className="mx-auto flex min-h-[60dvh] max-w-md flex-col items-center justify-center gap-3 p-6 text-center"
      >
        <h2 className="text-2xl font-semibold tracking-tight">
          {t("noPermissionTitle")}
        </h2>
        <p className="text-sm text-foreground/60">{t("noPermissionBody")}</p>
      </main>
    );
  }

  return <>{children}</>;
}
