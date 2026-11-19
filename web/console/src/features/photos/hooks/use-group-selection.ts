"use client";

import * as React from "react";

import {
  reconcileSelection,
  selectionOf,
  toggleProduct,
  type GroupSelection,
} from "../lib/group-selection";

export type GroupSelectionState = {
  ids: GroupSelection;
  selected: ReadonlySet<number>;
  count: number;
  toggle: (productId: number) => void;
  remove: (productId: number) => void;
  replace: (ids: readonly number[]) => void;
  reconcile: (linkedIds: readonly number[]) => void;
  clear: () => void;
};

export function useGroupSelection(
  initialIds: readonly number[] = [],
): GroupSelectionState {
  const [ids, setIds] = React.useState<GroupSelection>(() =>
    selectionOf(initialIds),
  );

  const selected = React.useMemo(() => new Set(ids), [ids]);

  return {
    ids,
    selected,
    count: ids.length,
    toggle: React.useCallback(
      (productId: number) =>
        setIds((current) => toggleProduct(current, productId)),
      [],
    ),
    remove: React.useCallback(
      (productId: number) =>
        setIds((current) => current.filter((id) => id !== productId)),
      [],
    ),
    replace: React.useCallback((next: readonly number[]) => {
      setIds(selectionOf(next));
    }, []),
    reconcile: React.useCallback((linkedIds: readonly number[]) => {
      setIds((current) => reconcileSelection(current, linkedIds));
    }, []),
    clear: React.useCallback(() => setIds([]), []),
  };
}
