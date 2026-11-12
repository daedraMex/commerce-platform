"use client";

import { useTranslations } from "next-intl";

import { useTheme } from "@/components/providers/theme-provider";
import type { ThemePreference } from "@/lib/theme";

export function ThemeSwitcher() {
  const t = useTranslations("Theme");
  const { preference, setPreference } = useTheme();

  return (
    <label className="flex items-center gap-2">
      <span className="sr-only">{t("label")}</span>
      <select
        aria-label={t("label")}
        className="h-9 rounded-md border border-border bg-background px-2 text-sm"
        value={preference}
        onChange={(event) =>
          setPreference(event.target.value as ThemePreference)
        }
      >
        <option value="light">{t("light")}</option>
        <option value="dark">{t("dark")}</option>
        <option value="system">{t("system")}</option>
      </select>
    </label>
  );
}
