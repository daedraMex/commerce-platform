import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PhotoSubmission } from "@commerce-platform/api-client";

import { usePhotoPolling } from "@/features/photos/hooks/use-photo-polling";
import { nextPollDelay } from "@/features/photos/lib/polling";

const { retrieve } = vi.hoisted(() => ({ retrieve: vi.fn() }));

vi.mock("@commerce-platform/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@commerce-platform/api-client")>()),
  apiV1StaffPhotosRetrieve: (...args: unknown[]) => retrieve(...args),
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient();
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderPolling(
  props: Omit<Parameters<typeof usePhotoPolling>[0], "store">,
) {
  return renderHook(
    (current: typeof props) => usePhotoPolling({ store: "anime", ...current }),
    { initialProps: props, wrapper },
  );
}

function submission(
  status: string,
  overrides: Partial<PhotoSubmission> = {},
): PhotoSubmission {
  return {
    attempts: 1,
    corners: null,
    created_at: "2026-11-12T09:30:00Z",
    crop: null,
    failure_code: "",
    failure_message: "",
    id: 1,
    kind: "rectangle",
    light_correction: true,
    linked_product_ids: [],
    photographed_variant_id: null,
    pipeline_version: "2026-11-11.2",
    preview_url: "/api/v1/staff/photos/1/preview/",
    redos: 0,
    redos_remaining: 5,
    result: null,
    status,
    target_product_id: 13,
    updated_at: "2026-11-12T09:31:15Z",
    version: 1,
    ...overrides,
  };
}

describe("nextPollDelay", () => {
  it("backs off from one second to eight seconds", () => {
    expect(nextPollDelay("uploaded", 0)).toBe(1000);
    expect(nextPollDelay("processing", 1)).toBe(2000);
    expect(nextPollDelay("processing", 2)).toBe(4000);
    expect(nextPollDelay("processing", 3)).toBe(8000);
    expect(nextPollDelay("processing", 12)).toBe(8000);
  });

  it("stops for terminal or missing statuses", () => {
    expect(nextPollDelay("ready", 0)).toBeNull();
    expect(nextPollDelay("failed", 0)).toBeNull();
    expect(nextPollDelay("discarded", 0)).toBeNull();
    expect(nextPollDelay(undefined, 0)).toBeNull();
  });

  it("stops for a discarded submission whose status is still processing", () => {
    expect(nextPollDelay("processing", 2, true)).toBeNull();
  });
});

describe("usePhotoPolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("polls with backoff and stops as soon as the photo is ready", async () => {
    retrieve
      .mockResolvedValueOnce(submission("processing"))
      .mockResolvedValueOnce(submission("processing"))
      .mockResolvedValueOnce(submission("ready"));
    const onUpdate = vi.fn();

    renderPolling({ submissionId: 1, status: "uploaded", onUpdate });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(retrieve).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(999);
    });
    expect(retrieve).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(retrieve).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1999);
    });
    expect(retrieve).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(retrieve).toHaveBeenCalledTimes(3);
    expect(onUpdate).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: "ready" }),
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(retrieve).toHaveBeenCalledTimes(3);
  });

  it("stops when the photo failed", async () => {
    retrieve.mockResolvedValueOnce(submission("failed"));
    const onUpdate = vi.fn();

    renderPolling({ submissionId: 1, status: "processing", onUpdate });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ status: "failed" }),
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(retrieve).toHaveBeenCalledTimes(1);
  });

  it("does not poll a discarded submission whose status is still processing", async () => {
    const onUpdate = vi.fn();

    renderPolling({
        submissionId: 1,
        status: "processing",
        discarded: true,
        onUpdate,
      });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(retrieve).not.toHaveBeenCalled();
  });

  it("stops when the server reports the submission discarded mid-poll", async () => {
    retrieve
      .mockResolvedValueOnce(submission("processing"))
      .mockResolvedValueOnce(
        submission("processing", { discarded_at: "2026-11-12T09:32:00Z" }),
      )
      .mockResolvedValue(submission("processing"));
    const onUpdate = vi.fn();

    renderPolling({ submissionId: 1, status: "uploaded", onUpdate });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(retrieve).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(retrieve).toHaveBeenCalledTimes(2);
    expect(onUpdate).toHaveBeenLastCalledWith(
      expect.objectContaining({ discarded_at: "2026-11-12T09:32:00Z" }),
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(retrieve).toHaveBeenCalledTimes(2);
  });

  it("restarts the backoff when a new processing attempt starts", async () => {
    retrieve.mockResolvedValue(submission("processing"));
    const onUpdate = vi.fn();

    const { rerender } = renderPolling({
      submissionId: 1,
      status: "processing",
      attempt: 1,
      onUpdate,
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0 + 1000 + 2000 + 4000);
    });
    expect(retrieve).toHaveBeenCalledTimes(4);

    rerender({ submissionId: 1, status: "processing", attempt: 2, onUpdate });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(retrieve).toHaveBeenCalledTimes(5);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(retrieve).toHaveBeenCalledTimes(6);
  });
});
