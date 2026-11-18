"use client";

import * as React from "react";

/**
 * A value and its debounced copy. The setter updates the value at once and schedules
 * the copy, so the debounce lives in the change handler instead of an effect (#166).
 */
export function useDebouncedState<T>(
  initial: T,
  delayMs: number,
): [value: T, debounced: T, setValue: (next: T) => void] {
  const [value, setValueState] = React.useState(initial);
  const [debounced, setDebounced] = React.useState(initial);
  const timer = React.useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const setValue = React.useCallback(
    (next: T) => {
      setValueState(next);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setDebounced(next), delayMs);
    },
    [delayMs],
  );

  return [value, debounced, setValue];
}
