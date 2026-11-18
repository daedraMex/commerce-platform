export type NormalizedPoint = {
  x: number;
  y: number;
};

export type NormalizedQuad = [
  NormalizedPoint,
  NormalizedPoint,
  NormalizedPoint,
  NormalizedPoint,
];

export type NormalizedCrop = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type PixelCrop = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export const DEFAULT_QUAD: NormalizedQuad = [
  { x: 0.1, y: 0.1 },
  { x: 0.9, y: 0.1 },
  { x: 0.9, y: 0.9 },
  { x: 0.1, y: 0.9 },
];

export const DEFAULT_CROP: NormalizedCrop = {
  x: 0.1,
  y: 0.1,
  width: 0.8,
  height: 0.8,
};

export function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

export function setCorner(
  quad: NormalizedQuad,
  index: number,
  point: NormalizedPoint,
): NormalizedQuad {
  return quad.map((corner, cornerIndex) =>
    cornerIndex === index
      ? { x: clamp01(point.x), y: clamp01(point.y) }
      : corner,
  ) as NormalizedQuad;
}

export function pointerToNormalized(
  bounds: { left: number; top: number; width: number; height: number },
  clientX: number,
  clientY: number,
): NormalizedPoint {
  if (bounds.width <= 0 || bounds.height <= 0) {
    return { x: 0, y: 0 };
  }

  return {
    x: clamp01((clientX - bounds.left) / bounds.width),
    y: clamp01((clientY - bounds.top) / bounds.height),
  };
}

export function cropToPixels(
  crop: NormalizedCrop,
  naturalWidth: number,
  naturalHeight: number,
): PixelCrop {
  return {
    x: Math.round(crop.x * naturalWidth),
    y: Math.round(crop.y * naturalHeight),
    width: Math.max(1, Math.round(crop.width * naturalWidth)),
    height: Math.max(1, Math.round(crop.height * naturalHeight)),
  };
}

export function pixelsToCrop(
  crop: PixelCrop,
  naturalWidth: number,
  naturalHeight: number,
): NormalizedCrop {
  if (naturalWidth <= 0 || naturalHeight <= 0) {
    return DEFAULT_CROP;
  }

  return {
    x: crop.x / naturalWidth,
    y: crop.y / naturalHeight,
    width: crop.width / naturalWidth,
    height: crop.height / naturalHeight,
  };
}

export function moveCrop(
  crop: NormalizedCrop,
  dx: number,
  dy: number,
): NormalizedCrop {
  return {
    ...crop,
    x: Math.min(Math.max(crop.x + dx, 0), 1 - crop.width),
    y: Math.min(Math.max(crop.y + dy, 0), 1 - crop.height),
  };
}

export type CropHandle = "nw" | "ne" | "sw" | "se";

export function resizeCrop(
  crop: NormalizedCrop,
  handle: CropHandle,
  dx: number,
  dy: number,
): NormalizedCrop {
  const minSize = 0.1;
  const left = crop.x;
  const top = crop.y;
  const right = crop.x + crop.width;
  const bottom = crop.y + crop.height;

  let nextLeft = left;
  let nextTop = top;
  let nextRight = right;
  let nextBottom = bottom;

  if (handle === "nw" || handle === "sw") {
    nextLeft = Math.min(Math.max(left + dx, 0), right - minSize);
  }
  if (handle === "ne" || handle === "se") {
    nextRight = Math.max(Math.min(right + dx, 1), left + minSize);
  }
  if (handle === "nw" || handle === "ne") {
    nextTop = Math.min(Math.max(top + dy, 0), bottom - minSize);
  }
  if (handle === "sw" || handle === "se") {
    nextBottom = Math.max(Math.min(bottom + dy, 1), top + minSize);
  }

  return {
    x: nextLeft,
    y: nextTop,
    width: nextRight - nextLeft,
    height: nextBottom - nextTop,
  };
}
