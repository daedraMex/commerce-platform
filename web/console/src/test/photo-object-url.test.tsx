import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useObjectUrl } from "@/features/photos/hooks/use-object-url";

describe("useObjectUrl", () => {
  const createObjectURL = vi.fn();
  const revokeObjectURL = vi.fn();
  const originalCreate = URL.createObjectURL;
  const originalRevoke = URL.revokeObjectURL;

  beforeEach(() => {
    let counter = 0;
    createObjectURL.mockReset();
    revokeObjectURL.mockReset();
    createObjectURL.mockImplementation(() => `blob:preview-${++counter}`);
    URL.createObjectURL = createObjectURL;
    URL.revokeObjectURL = revokeObjectURL;
  });

  afterEach(() => {
    URL.createObjectURL = originalCreate;
    URL.revokeObjectURL = originalRevoke;
  });

  it("creates an object URL and revokes it on unmount", () => {
    const blob = new Blob(["preview"], { type: "image/jpeg" });
    const { result, unmount } = renderHook(() => useObjectUrl(blob));

    expect(createObjectURL).toHaveBeenCalledWith(blob);
    expect(result.current).toBe("blob:preview-1");

    unmount();

    expect(revokeObjectURL).toHaveBeenCalledWith("blob:preview-1");
  });

  it("revokes the previous URL when the preview is replaced", () => {
    const first = new Blob(["first"], { type: "image/jpeg" });
    const second = new Blob(["second"], { type: "image/jpeg" });
    const { result, rerender } = renderHook(
      ({ blob }: { blob: Blob }) => useObjectUrl(blob),
      { initialProps: { blob: first } },
    );

    expect(result.current).toBe("blob:preview-1");

    rerender({ blob: second });

    expect(revokeObjectURL).toHaveBeenCalledWith("blob:preview-1");
    expect(result.current).toBe("blob:preview-2");
  });

  it("revokes the URL when the preview disappears", () => {
    const blob = new Blob(["preview"], { type: "image/jpeg" });
    const { result, rerender } = renderHook(
      ({ value }: { value: Blob | null }) => useObjectUrl(value),
      { initialProps: { value: blob as Blob | null } },
    );

    rerender({ value: null });

    expect(revokeObjectURL).toHaveBeenCalledWith("blob:preview-1");
    expect(result.current).toBeNull();
  });
});
