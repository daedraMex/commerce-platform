const signalStores = new WeakMap<AbortSignal, string>();

let currentStore: string | undefined;

export function setCurrentStore(store: string | undefined): void {
  currentStore = store;
}

export function getCurrentStore(): string | undefined {
  return currentStore;
}

export function clearCurrentStore(store?: string): void {
  if (store === undefined || currentStore === store) {
    currentStore = undefined;
  }
}

/** Ties the store that owns a query to the signal React Query hands it. */
export function bindStoreToSignal(
  signal: AbortSignal | null | undefined,
  store: string,
): void {
  if (signal) {
    signalStores.set(signal, store);
  }
}

export function getStoreFromSignal(
  signal: AbortSignal | null | undefined,
): string | undefined {
  return signal ? signalStores.get(signal) : undefined;
}
