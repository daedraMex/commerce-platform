"use client";

import * as React from "react";
import { useTranslations } from "next-intl";

import type { MeMembership } from "@commerce-platform/api-client";

import { Button } from "@/components/atoms/button";
import { StoreSwitcher } from "@/components/molecules/store-switcher";
import { ThemeSwitcher } from "@/components/molecules/theme-switcher";
import { ConsoleMenu } from "@/components/organisms/console-menu";
import { accentColor, accentForeground } from "@/lib/theme";

type ConsoleShellProps = {
  store: string;
  membership: MeMembership;
  memberships: MeMembership[];
  userEmail: string;
  signingOut: boolean;
  onSignOut: () => void;
  children: React.ReactNode;
};

export function ConsoleShell({
  store,
  membership,
  memberships,
  userEmail,
  signingOut,
  onSignOut,
  children,
}: ConsoleShellProps) {
  const t = useTranslations("Session");
  const accent = accentColor(membership.store.accent_color);
  const style = {
    "--accent": accent,
    "--accent-foreground": accentForeground(accent),
  } as React.CSSProperties;

  return (
    <div
      data-console-shell=""
      data-store={store}
      style={style}
      className="min-h-dvh bg-background text-foreground"
    >
      <header className="sticky top-0 z-20 border-b border-border bg-background/95 backdrop-blur">
        <div className="h-1 bg-accent" aria-hidden="true" />
        <div className="flex flex-wrap items-center gap-2 px-3 py-3 sm:px-4">
          <div className="mr-auto min-w-0">
            <h1 className="text-lg font-semibold tracking-tight">Quetzal</h1>
            <p className="truncate text-xs text-foreground/60">{userEmail}</p>
          </div>
          <StoreSwitcher store={store} memberships={memberships} />
          <ThemeSwitcher />
          <Button
            variant="ghost"
            size="sm"
            onClick={onSignOut}
            disabled={signingOut}
          >
            {t("signOut")}
          </Button>
        </div>
        <ConsoleMenu store={store} permissions={membership.permissions} />
      </header>
      {children}
    </div>
  );
}
