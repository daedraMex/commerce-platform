import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDebouncedState } from "@/features/photos/hooks/use-debounced-state";

describe("useDebouncedState", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("updates the value at once and the debounced copy after the delay", () => {
    const { result } = renderHook(() => useDebouncedState("", 250));

    act(() => result.current[2]("ta"));
    expect(result.current[0]).toBe("ta");
    expect(result.current[1]).toBe("");

    act(() => vi.advanceTimersByTime(249));
    expect(result.current[1]).toBe("");

    act(() => vi.advanceTimersByTime(1));
    expect(result.current[1]).toBe("ta");
  });

  it("keeps only the last value typed within the delay", () => {
    const { result } = renderHook(() => useDebouncedState("", 250));

    act(() => result.current[2]("t"));
    act(() => vi.advanceTimersByTime(200));
    act(() => result.current[2]("taz"));
    act(() => vi.advanceTimersByTime(200));
    expect(result.current[1]).toBe("");

    act(() => vi.advanceTimersByTime(50));
    expect(result.current[1]).toBe("taz");
  });
});
