import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useGroupSelection } from "@/features/photos/hooks/use-group-selection";
import {
  reconcileSelection,
  toggleProduct,
} from "@/features/photos/lib/group-selection";

describe("group selection order", () => {
  it("toggles a product on at the end and removes it without reordering the rest", () => {
    const first = toggleProduct([], 13);
    const second = toggleProduct(first, 12);
    const third = toggleProduct(second, 15);

    expect(first).toEqual([13]);
    expect(second).toEqual([13, 12]);
    expect(third).toEqual([13, 12, 15]);

    expect(toggleProduct(third, 12)).toEqual([13, 15]);
    expect(toggleProduct(toggleProduct(third, 12), 12)).toEqual([
      13,
      15,
      12,
    ]);
  });

  it("keeps retained links in order and appends newly linked products", () => {
    expect(reconcileSelection([12, 13, 14], [14, 12, 15])).toEqual([
      12,
      14,
      15,
    ]);
  });

  it("drops products that are no longer linked", () => {
    expect(reconcileSelection([13, 12, 15], [15])).toEqual([15]);
  });
});

describe("useGroupSelection", () => {
  it("appends new products, removes existing ones and reconciles with the server", () => {
    const { result } = renderHook(() => useGroupSelection([13]));

    expect(result.current.ids).toEqual([13]);
    expect(result.current.count).toBe(1);
    expect(result.current.selected.has(13)).toBe(true);

    act(() => result.current.toggle(12));
    expect(result.current.ids).toEqual([13, 12]);

    act(() => result.current.toggle(13));
    expect(result.current.ids).toEqual([12]);
    expect(result.current.selected.has(13)).toBe(false);

    act(() => result.current.toggle(13));
    expect(result.current.ids).toEqual([12, 13]);

    act(() => result.current.reconcile([13, 12, 14]));
    expect(result.current.ids).toEqual([12, 13, 14]);

    act(() => result.current.remove(13));
    expect(result.current.ids).toEqual([12, 14]);

    act(() => result.current.clear());
    expect(result.current.count).toBe(0);
  });

  it("normalizes duplicates and invalid ids", () => {
    const { result } = renderHook(() => useGroupSelection([12, 12, -1, 13]));

    expect(result.current.ids).toEqual([12, 13]);
  });
});
