export type PhotoUploadKey = {
  file: File;
  key: string;
};

export function createIdempotencyKey(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }

  return `photo-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2)}`;
}

export function reuseOrCreateUploadKey(
  current: PhotoUploadKey | null,
  file: File,
  create: () => string = createIdempotencyKey,
): PhotoUploadKey {
  if (current && current.file === file) {
    return current;
  }

  return { file, key: create() };
}
