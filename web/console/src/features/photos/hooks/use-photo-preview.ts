"use client";

import { useApiV1StaffPhotosPreviewRetrieve } from "@commerce-platform/api-client";

import { useObjectUrl } from "./use-object-url";

export function usePhotoPreview(
  submissionId: number | null,
  enabled: boolean,
): string | null {
  const preview = useApiV1StaffPhotosPreviewRetrieve(submissionId ?? 0, {
    query: {
      enabled: submissionId !== null && enabled,
      retry: false,
    },
  });

  return useObjectUrl(enabled ? preview.data : undefined);
}
