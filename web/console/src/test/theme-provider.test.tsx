import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ThemeProvider, useTheme } from "@/components/providers/theme-provider";

type Listener = (event: MediaQueryListEvent) => void;

function fakeMatchMedia(initiallyDark: boolean) {
  let matches = initiallyDark;
  const listeners = new Set<Listener>();
  const media = {
    get matches() {
      return matches;
    },
    addEventListener: (_type: string, listener: Listener) => listeners.add(listener),
    removeEventListener: (_type: string, listener: Listener) => listeners.delete(listener),
  };
  vi.stubGlobal("matchMedia", () => media);
  return {
    listeners,
    setDark(next: boolean) {
      matches = next;
      listeners.forEach((listener) => listener({ matches: next } as MediaQueryListEvent));
    },
  };
}

function Resolved() {
  return <span>{useTheme().resolved}</span>;
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("ThemeProvider", () => {
  it("follows the system preference while the preference is system", () => {
    const system = fakeMatchMedia(false);
    render(
      <ThemeProvider>
        <Resolved />
      </ThemeProvider>,
    );
    expect(screen.getByText("light")).toBeInTheDocument();

    act(() => system.setDark(true));

    expect(screen.getByText("dark")).toBeInTheDocument();
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("stops listening when it unmounts", () => {
    const system = fakeMatchMedia(false);
    const { unmount } = render(
      <ThemeProvider>
        <Resolved />
      </ThemeProvider>,
    );
    expect(system.listeners.size).toBeGreaterThan(0);

    unmount();

    expect(system.listeners.size).toBe(0);
  });
});
