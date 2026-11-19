import { describe, expect, it } from "vitest";

import {
  cropAspectScale,
  cropForAspect,
  GROUP_CROP_ASPECT,
  resizeCropToAspect,
  type NormalizedCrop,
} from "@/features/photos/lib/geometry";

function pixelRatio(
  crop: NormalizedCrop,
  width: number,
  height: number,
): number {
  return (crop.width * width) / (crop.height * height);
}

describe("group photo crop", () => {
  it("fits the largest centred 4:5 crop inside a landscape photo", () => {
    const crop = cropForAspect(1600, 1200, GROUP_CROP_ASPECT);

    expect(crop).toMatchObject({
      x: 0.2,
      y: 0,
      width: 0.6,
      height: 1,
    });
    expect(pixelRatio(crop, 1600, 1200)).toBeCloseTo(0.8, 6);
  });

  it("fits the largest centred 4:5 crop inside a portrait photo", () => {
    const crop = cropForAspect(1000, 1500, GROUP_CROP_ASPECT);

    expect(crop.x).toBe(0);
    expect(crop.y).toBeCloseTo(0.0833, 4);
    expect(crop.width).toBe(1);
    expect(crop.height).toBeCloseTo(0.8333, 4);
    expect(pixelRatio(crop, 1000, 1500)).toBeCloseTo(0.8, 3);
  });

  it("resizes from a corner without leaving the photo or losing 4:5", () => {
    const scale = cropAspectScale(1600, 1200, GROUP_CROP_ASPECT);
    const crop = cropForAspect(1600, 1200, GROUP_CROP_ASPECT);

    const resized = resizeCropToAspect(crop, "se", -0.1, -0.15, scale);

    expect(resized.x).toBeGreaterThanOrEqual(0);
    expect(resized.y).toBeGreaterThanOrEqual(0);
    expect(resized.x + resized.width).toBeLessThanOrEqual(1);
    expect(resized.y + resized.height).toBeLessThanOrEqual(1);
    expect(resized.width).toBeLessThan(crop.width);
    expect(pixelRatio(resized, 1600, 1200)).toBeCloseTo(0.8, 6);
  });

  it("moves a crop without changing its 4:5 ratio", () => {
    const crop = cropForAspect(1600, 1200, GROUP_CROP_ASPECT);
    const moved = { ...crop, x: 0.4 };
    expect(pixelRatio(moved, 1600, 1200)).toBeCloseTo(0.8, 6);
  });
});
