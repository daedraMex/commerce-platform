import { describe, expect, it, vi } from "vitest";

import {
  reuseOrCreateUploadKey,
  type PhotoUploadKey,
} from "@/features/photos/lib/idempotency";

function imageFile(name = "photo.jpg"): File {
  return new File(["photo"], name, { type: "image/jpeg" });
}

describe("reuseOrCreateUploadKey", () => {
  it("reuses the key for retries and double taps of the same photo", () => {
    const file = imageFile();
    const create = vi.fn(() => "key-1");

    const first = reuseOrCreateUploadKey(null, file, create);
    const retry = reuseOrCreateUploadKey(first, file, create);
    const doubleTap = reuseOrCreateUploadKey(retry, file, create);

    expect(first).toEqual({ file, key: "key-1" });
    expect(retry).toBe(first);
    expect(doubleTap).toBe(first);
    expect(create).toHaveBeenCalledTimes(1);
  });

  it("creates a fresh key when the staff member chooses another photo", () => {
    const firstFile = imageFile("first.jpg");
    const secondFile = imageFile("second.jpg");
    const create = vi
      .fn()
      .mockReturnValueOnce("key-1")
      .mockReturnValueOnce("key-2");

    const first: PhotoUploadKey = reuseOrCreateUploadKey(
      null,
      firstFile,
      create,
    );
    const second = reuseOrCreateUploadKey(first, secondFile, create);

    expect(second).toEqual({ file: secondFile, key: "key-2" });
    expect(create).toHaveBeenCalledTimes(2);
  });
});
