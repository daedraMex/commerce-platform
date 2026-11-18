export type GroupSelection = number[];

function normalizeIds(ids: readonly number[]): GroupSelection {
  const seen = new Set<number>();
  const result: GroupSelection = [];
  for (const id of ids) {
    if (Number.isInteger(id) && id > 0 && !seen.has(id)) {
      seen.add(id);
      result.push(id);
    }
  }
  return result;
}

export function toggleProduct(
  selection: readonly number[],
  productId: number,
): GroupSelection {
  if (selection.includes(productId)) {
    return selection.filter((id) => id !== productId);
  }
  return [...selection, productId];
}

/**
 * Keep the order already chosen by staff for retained products and append new
 * server links after them; nothing that is no longer linked survives.
 */
export function reconcileSelection(
  selection: readonly number[],
  linkedIds: readonly number[],
): GroupSelection {
  const linked = normalizeIds(linkedIds);
  const linkedSet = new Set(linked);
  const retained = normalizeIds(selection).filter((id) => linkedSet.has(id));
  const retainedSet = new Set(retained);
  return [...retained, ...linked.filter((id) => !retainedSet.has(id))];
}

export function selectionOf(ids: readonly number[]): GroupSelection {
  return normalizeIds(ids);
}
