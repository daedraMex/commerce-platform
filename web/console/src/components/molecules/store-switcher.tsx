"use client";

import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import type { MeMembership } from "@commerce-platform/api-client";

import { storeHref, swapStoreInPath } from "@/lib/store-path";

type StoreSwitcherProps = {
  store: string;
  memberships: MeMembership[];
};

export function StoreSwitcher({ store, memberships }: StoreSwitcherProps) {
  const t = useTranslations("StoreSwitcher");
  const router = useRouter();
  const pathname = usePathname() ?? storeHref(store, "");

  const onChange = (nextStore: string) => {
    if (nextStore === store) {
      return;
    }

    const search = window.location.search;
    const hash = window.location.hash;
    router.push(`${swapStoreInPath(pathname, nextStore)}${search}${hash}`);
  };

  return (
    <label className="flex items-center gap-2">
      <span className="sr-only">{t("label")}</span>
      <select
        aria-label={t("label")}
        className="h-9 max-w-40 rounded-md border border-accent bg-background px-2 text-sm font-medium"
        value={store}
        onChange={(event) => onChange(event.target.value)}
      >
        {memberships.map((membership) => (
          <option key={membership.store.slug} value={membership.store.slug}>
            {membership.store.name}
          </option>
        ))}
      </select>
    </label>
  );
}
