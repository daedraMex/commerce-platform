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

const CROP_ASPECT_WIDTH = 4;
const CROP_ASPECT_HEIGHT = 5;

/** The 4:5 ratio shared by group photos and individual contour photos. */
export const CROP_ASPECT = CROP_ASPECT_WIDTH / CROP_ASPECT_HEIGHT;

/**
 * Normalized height per normalized width that makes a crop 4:5 in pixels:
 * (width * imageWidth) / (height * imageHeight) = aspect, so height = width * scale.
 */
export function cropAspectScale(
  imageWidth: number,
  imageHeight: number,
  aspect: number,
): number {
  if (imageWidth <= 0 || imageHeight <= 0 || aspect <= 0) {
    return 1;
  }

  return imageWidth / (aspect * imageHeight);
}

/** The largest centred crop at the target pixel aspect ratio inside the photo. */
export function cropForAspect(
  imageWidth: number,
  imageHeight: number,
  aspect: number,
): NormalizedCrop {
  const scale = cropAspectScale(imageWidth, imageHeight, aspect);
  const width = Math.min(1, 1 / scale);
  const height = width * scale;

  return {
    x: (1 - width) / 2,
    y: (1 - height) / 2,
    width,
    height,
  };
}

/**
 * Fit an integer pixel crop to the exact 4:5 ratio inside the image, keeping its centre.
 * Exact integer units make the worker's `fit_crop` return the rectangle unchanged.
 */
export function fitPixelCropToAspect(
  crop: PixelCrop,
  imageWidth: number,
  imageHeight: number,
): PixelCrop {
  if (imageWidth <= 0 || imageHeight <= 0) {
    return crop;
  }

  const maxUnits = Math.floor(
    Math.min(imageWidth / CROP_ASPECT_WIDTH, imageHeight / CROP_ASPECT_HEIGHT),
  );
  if (maxUnits < 1) {
    return crop;
  }

  const desiredUnits = Math.min(
    crop.width / CROP_ASPECT_WIDTH,
    crop.height / CROP_ASPECT_HEIGHT,
  );
  const units = Math.min(maxUnits, Math.max(1, Math.round(desiredUnits)));
  const width = units * CROP_ASPECT_WIDTH;
  const height = units * CROP_ASPECT_HEIGHT;
  const x = Math.min(
    Math.max(Math.round(crop.x + (crop.width - width) / 2), 0),
    imageWidth - width,
  );
  const y = Math.min(
    Math.max(Math.round(crop.y + (crop.height - height) / 2), 0),
    imageHeight - height,
  );

  return { x, y, width, height };
}

/** Resize a crop while keeping it at the target pixel aspect ratio. */
export function resizeCropToAspect(
  crop: NormalizedCrop,
  handle: CropHandle,
  dx: number,
  dy: number,
  aspectScale: number,
): NormalizedCrop {
  if (aspectScale <= 0) {
    return crop;
  }

  const east = handle === "ne" || handle === "se";
  const south = handle === "sw" || handle === "se";
  const right = crop.x + crop.width;
  const bottom = crop.y + crop.height;

  let width = east ? crop.width + dx : crop.width - dx;
  if (Math.abs(dy) > Math.abs(dx)) {
    const height = south ? crop.height + dy : crop.height - dy;
    width = height / aspectScale;
  }

  const maxWidthByX = east ? 1 - crop.x : right;
  const maxWidthByY = (south ? 1 - crop.y : bottom) / aspectScale;
  const maxWidth = Math.max(0.01, Math.min(maxWidthByX, maxWidthByY));
  const minWidth = Math.min(0.1, maxWidth);
  width = Math.min(maxWidth, Math.max(minWidth, width));

  const height = width * aspectScale;
  return {
    x: east ? crop.x : right - width,
    y: south ? crop.y : bottom - height,
    width,
    height,
  };
}
