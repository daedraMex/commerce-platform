"use client";

import { useQueryClient } from "@tanstack/react-query";
import { redirect, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { useApiV1MeRetrieve } from "@commerce-platform/api-client";

import { Button } from "@/components/atoms/button";
import { ConsoleShell } from "@/components/templates/console-shell";
import { CSRF_HEADER, CSRF_HEADER_VALUE } from "@/lib/auth/constants";
import { SESSION_STALE_TIME_MS } from "../lib/session-query";

type SessionGateProps = {
  store: string;
  children: React.ReactNode;
};

type RequestError = {
  response?: { status?: number };
};

function statusOf(error: unknown): number | undefined {
  return (error as RequestError | null)?.response?.status;
}

export function SessionGate({ store, children }: SessionGateProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const t = useTranslations("Session");
  const [signingOut, setSigningOut] = React.useState(false);
  const [signOutStarted, setSignOutStarted] = React.useState(false);

  const { data, error, isPending } = useApiV1MeRetrieve({
    query: { retry: false, staleTime: SESSION_STALE_TIME_MS },
  });

  const memberships = React.useMemo(() => data?.memberships ?? [], [data]);
  const membership = memberships.find((item) => item.store.slug === store);
  const unauthorized = statusOf(error) === 401 || statusOf(error) === 403;
  const unknownStore = data !== undefined && memberships.length > 0 && !membership;

  if (unauthorized) {
    if (!signOutStarted) {
      redirect(`/sign-in?next=${encodeURIComponent(`/${store}`)}`);
    }
    return null;
  }

  if (unknownStore) {
    redirect(`/${memberships[0].store.slug}`);
  }

  const signOut = async () => {
    setSignOutStarted(true);
    setSigningOut(true);
    try {
      await fetch("/api/auth/sign-out", {
        method: "POST",
        headers: { [CSRF_HEADER]: CSRF_HEADER_VALUE },
      });
      queryClient.clear();
      router.replace("/sign-in");
      router.refresh();
    } finally {
      setSigningOut(false);
    }
  };

  if (unauthorized || unknownStore) {
    return null;
  }

  if (isPending) {
    return (
      <main className="mx-auto flex min-h-dvh max-w-md items-center justify-center p-6 text-sm">
        {t("loading")}
      </main>
    );
  }

  if (error) {
    return (
      <main className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-4 p-6 text-center">
        <p className="text-sm">{t("error")}</p>
        <Button variant="outline" onClick={() => router.refresh()}>
          {t("retry")}
        </Button>
      </main>
    );
  }

  if (data && !membership) {
    return (
      <main className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-4 p-6 text-center">
        <h1 className="text-2xl font-semibold">{t("noStoresTitle")}</h1>
        <p className="text-sm">{t("noStoresBody")}</p>
        <Button variant="outline" onClick={signOut} disabled={signingOut}>
          {t("signOut")}
        </Button>
      </main>
    );
  }

  if (!data || !membership) {
    return null;
  }

  return (
    <ConsoleShell
      store={store}
      membership={membership}
      memberships={memberships}
      userEmail={data.user.email}
      signingOut={signingOut}
      onSignOut={signOut}
    >
      {children}
    </ConsoleShell>
  );
}
