export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "quetzal_theme";
export const DEFAULT_ACCENT = "#4f46e5";

const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;

export const THEME_INIT_SCRIPT = `(function(){try{var preference=localStorage.getItem(${JSON.stringify(
  THEME_STORAGE_KEY,
)});var dark=preference==="dark"||(preference!=="light"&&window.matchMedia("(prefers-color-scheme: dark)").matches);var root=document.documentElement;root.classList.toggle("dark",dark);root.style.colorScheme=dark?"dark":"light";}catch(error){}})();`;

export function parseThemePreference(value: string | null): ThemePreference {
  if (value === "light" || value === "dark" || value === "system") {
    return value;
  }
  return "system";
}

export function resolveTheme(
  preference: ThemePreference,
  systemPrefersDark: boolean,
): ResolvedTheme {
  if (preference === "system") {
    return systemPrefersDark ? "dark" : "light";
  }
  return preference;
}

export function applyThemeToDocument(
  theme: ResolvedTheme,
  documentElement: HTMLElement = document.documentElement,
): void {
  documentElement.classList.toggle("dark", theme === "dark");
  documentElement.style.colorScheme = theme;
}

export function accentColor(value: string | undefined): string {
  return value && HEX_COLOR.test(value) ? value.toLowerCase() : DEFAULT_ACCENT;
}

function channel(component: number): number {
  const value = component / 255;
  return value <= 0.03928
    ? value / 12.92
    : Math.pow((value + 0.055) / 1.055, 2.4);
}

function luminance(hex: string): number {
  const [red, green, blue] = [1, 3, 5].map((offset) =>
    channel(Number.parseInt(hex.slice(offset, offset + 2), 16)),
  );
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function contrastRatio(first: number, second: number): number {
  const lighter = Math.max(first, second);
  const darker = Math.min(first, second);
  return (lighter + 0.05) / (darker + 0.05);
}

export function accentForeground(value: string): "#000000" | "#ffffff" {
  const colorLuminance = luminance(accentColor(value));
  const onWhite = contrastRatio(1, colorLuminance);
  const onBlack = contrastRatio(colorLuminance, 0);
  return onWhite >= onBlack ? "#ffffff" : "#000000";
}
