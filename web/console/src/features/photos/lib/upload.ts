import {
  apiClient,
  type KindEnum,
  type PhotoSubmission,
} from "@commerce-platform/api-client";

import type { NormalizedQuad, PixelCrop } from "./geometry";

export type PhotoUploadRequest = {
  file: File;
  kind: KindEnum;
  targetProductId?: number | null;
  idempotencyKey: string;
  lightCorrection: boolean;
  corners?: NormalizedQuad;
  crop?: PixelCrop;
};

export type PhotoRedoRequest = {
  id: number;
  corners?: NormalizedQuad;
  crop?: PixelCrop;
};

export function buildPhotoUploadForm(input: PhotoUploadRequest): FormData {
  const body = new FormData();
  body.append("file", input.file);
  body.append("kind", input.kind);
  if (input.targetProductId !== undefined && input.targetProductId !== null) {
    body.append("target_product", String(input.targetProductId));
  }
  body.append("light_correction", String(input.lightCorrection));
  if (input.corners) {
    body.append("corners", JSON.stringify(input.corners));
  }
  if (input.crop) {
    body.append("crop", JSON.stringify(input.crop));
  }
  return body;
}

export function uploadPhoto(
  input: PhotoUploadRequest,
): Promise<PhotoSubmission> {
  return apiClient<PhotoSubmission>({
    url: "/api/v1/staff/photos",
    method: "POST",
    headers: { "Idempotency-Key": input.idempotencyKey },
    data: buildPhotoUploadForm(input),
  });
}

export function redoPhoto({
  id,
  corners,
  crop,
}: PhotoRedoRequest): Promise<PhotoSubmission> {
  const body: { corners?: NormalizedQuad; crop?: PixelCrop } = {};
  if (corners) {
    body.corners = corners;
  }
  if (crop) {
    body.crop = crop;
  }

  return apiClient<PhotoSubmission>({
    url: `/api/v1/staff/photos/${id}/redo`,
    method: "POST",
    data: body,
  });
}
