import { describe, expect, it } from "vitest";

import {
  DEFAULT_ACCENT,
  THEME_STORAGE_KEY,
  accentColor,
  accentForeground,
  applyThemeToDocument,
  parseThemePreference,
  resolveTheme,
} from "@/lib/theme";

describe("parseThemePreference", () => {
  it("falls back to system for missing or unknown values", () => {
    expect(parseThemePreference(null)).toBe("system");
    expect(parseThemePreference("")).toBe("system");
    expect(parseThemePreference("sepia")).toBe("system");
  });

  it("accepts the three preferences", () => {
    expect(parseThemePreference("light")).toBe("light");
    expect(parseThemePreference("dark")).toBe("dark");
    expect(parseThemePreference("system")).toBe("system");
  });
});

describe("resolveTheme", () => {
  it("follows the system only when asked to", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
    expect(resolveTheme("light", true)).toBe("light");
  });
});

describe("applyThemeToDocument", () => {
  it("toggles the dark class and color scheme", () => {
    applyThemeToDocument("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.style.colorScheme).toBe("dark");

    applyThemeToDocument("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(document.documentElement.style.colorScheme).toBe("light");
  });
});

describe("accent color", () => {
  it("normalizes a valid six-digit hex color", () => {
    expect(accentColor("#4F46E5")).toBe("#4f46e5");
    expect(accentColor("#0EA5E9")).toBe("#0ea5e9");
  });

  it("falls back for missing or invalid values", () => {
    expect(accentColor(undefined)).toBe(DEFAULT_ACCENT);
    expect(accentColor("red")).toBe(DEFAULT_ACCENT);
    expect(accentColor("#fff")).toBe(DEFAULT_ACCENT);
    expect(accentColor("#4f46e5; background: red")).toBe(DEFAULT_ACCENT);
  });

  it("picks a readable foreground", () => {
    expect(accentForeground("#ffffff")).toBe("#000000");
    expect(accentForeground("#000000")).toBe("#ffffff");
    expect(accentForeground("#4f46e5")).toBe("#ffffff");
    expect(accentForeground("#0ea5e9")).toBe("#000000");
  });

  it("uses the persisted preference key", () => {
    expect(THEME_STORAGE_KEY).toBe("quetzal_theme");
  });
});
