let currentStore: string | undefined;

export function setCurrentStore(store: string | undefined): void {
  currentStore = store;
}

export function getCurrentStore(): string | undefined {
  return currentStore;
}

export function clearCurrentStore(): void {
  currentStore = undefined;
}
