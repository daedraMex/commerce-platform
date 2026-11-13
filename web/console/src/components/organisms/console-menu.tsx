"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import { menuItemsFor } from "@/lib/menu";
import { storeHref } from "@/lib/store-path";

type ConsoleMenuProps = {
  store: string;
  permissions: string[];
};

export function ConsoleMenu({ store, permissions }: ConsoleMenuProps) {
  const t = useTranslations("Navigation");
  const pathname = usePathname() ?? storeHref(store, "");
  const current = pathname.replace(/\/+$/, "") || "/";
  const items = menuItemsFor(permissions);

  return (
    <nav
      aria-label={t("label")}
      className="flex gap-1 overflow-x-auto px-2 pb-2"
    >
      {items.map((item) => {
        const href = storeHref(store, item.segment);
        const active =
          item.segment.length === 0
            ? current === href
            : current === href || current.startsWith(`${href}/`);

        return (
          <Link
            key={item.segment || "home"}
            href={href}
            aria-current={active ? "page" : undefined}
            className={
              active
                ? "whitespace-nowrap rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-foreground"
                : "whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium text-foreground/70 hover:bg-foreground/5 hover:text-foreground"
            }
          >
            {t(item.labelKey)}
          </Link>
        );
      })}
    </nav>
  );
}
