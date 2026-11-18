"use client";

import * as React from "react";
import { useTranslations } from "next-intl";

import {
  moveCrop,
  pixelsToCrop,
  pointerToNormalized,
  resizeCrop,
  setCorner,
  type CropHandle,
  type NormalizedCrop,
  type NormalizedPoint,
  type NormalizedQuad,
  type PixelCrop,
} from "../lib/geometry";

type PhotoShape = "rectangle" | "contour";

type PhotoEditorProps = {
  imageUrl: string;
  shape: PhotoShape;
  corners: NormalizedQuad;
  crop: NormalizedCrop;
  lightCorrection: boolean;
  initialPixelCrop?: PixelCrop | null;
  onCornersChange: (corners: NormalizedQuad) => void;
  onCropChange: (crop: NormalizedCrop) => void;
  onLightCorrectionChange: (enabled: boolean) => void;
  onNaturalSize?: (size: { width: number; height: number }) => void;
};

type Bounds = {
  left: number;
  top: number;
  width: number;
  height: number;
};

type QuadDrag = {
  index: number;
  bounds: Bounds;
};

type CropDrag =
  | {
      mode: "move";
      bounds: Bounds;
      start: NormalizedPoint;
      startCrop: NormalizedCrop;
    }
  | {
      mode: "resize";
      handle: CropHandle;
      bounds: Bounds;
      start: NormalizedPoint;
      startCrop: NormalizedCrop;
    };

function boundsOf(element: HTMLElement): Bounds {
  const rect = element.getBoundingClientRect();
  return {
    left: rect.left,
    top: rect.top,
    width: rect.width,
    height: rect.height,
  };
}

export function PhotoEditor({
  imageUrl,
  shape,
  corners,
  crop,
  lightCorrection,
  initialPixelCrop,
  onCornersChange,
  onCropChange,
  onLightCorrectionChange,
  onNaturalSize,
}: PhotoEditorProps) {
  const t = useTranslations("Photos");
  const canvasRef = React.useRef<HTMLDivElement>(null);
  const initializedCrop = React.useRef(false);
  const [quadDrag, setQuadDrag] = React.useState<QuadDrag | null>(null);
  const [loupePoint, setLoupePoint] = React.useState<NormalizedPoint | null>(
    null,
  );
  const [cropDrag, setCropDrag] = React.useState<CropDrag | null>(null);

  const handleImageLoad = (event: React.SyntheticEvent<HTMLImageElement>) => {
    const image = event.currentTarget;
    const naturalWidth = image.naturalWidth;
    const naturalHeight = image.naturalHeight;
    onNaturalSize?.({ width: naturalWidth, height: naturalHeight });

    if (
      !initializedCrop.current &&
      initialPixelCrop &&
      naturalWidth > 0 &&
      naturalHeight > 0
    ) {
      initializedCrop.current = true;
      onCropChange(
        pixelsToCrop(initialPixelCrop, naturalWidth, naturalHeight),
      );
    }
  };

  const updateQuad = (
    index: number,
    bounds: Bounds,
    clientX: number,
    clientY: number,
  ) => {
    const point = pointerToNormalized(bounds, clientX, clientY);
    onCornersChange(setCorner(corners, index, point));
    setLoupePoint(point);
  };

  const quadPointerDown =
    (index: number) => (event: React.PointerEvent<HTMLDivElement>) => {
      if (!canvasRef.current) {
        return;
      }
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      setQuadDrag({ index, bounds: boundsOf(canvasRef.current) });
      updateQuad(index, boundsOf(canvasRef.current), event.clientX, event.clientY);
    };

  const quadPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!quadDrag) {
      return;
    }
    event.preventDefault();
    updateQuad(quadDrag.index, quadDrag.bounds, event.clientX, event.clientY);
  };

  const quadPointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!quadDrag) {
      return;
    }
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setQuadDrag(null);
    setLoupePoint(null);
  };

  const cropPointerDownMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!canvasRef.current) {
      return;
    }
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const bounds = boundsOf(canvasRef.current);
    setCropDrag({
      mode: "move",
      bounds,
      start: pointerToNormalized(bounds, event.clientX, event.clientY),
      startCrop: crop,
    });
  };

  const cropPointerDownHandle =
    (handle: CropHandle) => (event: React.PointerEvent<HTMLDivElement>) => {
      if (!canvasRef.current) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      event.currentTarget.setPointerCapture(event.pointerId);
      const bounds = boundsOf(canvasRef.current);
      setCropDrag({
        mode: "resize",
        handle,
        bounds,
        start: pointerToNormalized(bounds, event.clientX, event.clientY),
        startCrop: crop,
      });
    };

  const cropPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!cropDrag) {
      return;
    }
    event.preventDefault();
    const point = pointerToNormalized(
      cropDrag.bounds,
      event.clientX,
      event.clientY,
    );
    const dx = point.x - cropDrag.start.x;
    const dy = point.y - cropDrag.start.y;
    onCropChange(
      cropDrag.mode === "move"
        ? moveCrop(cropDrag.startCrop, dx, dy)
        : resizeCrop(cropDrag.startCrop, cropDrag.handle, dx, dy),
    );
  };

  const cropPointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setCropDrag(null);
  };

  const points = [
    { x: corners[0].x, y: corners[0].y },
    { x: corners[1].x, y: corners[1].y },
    { x: corners[2].x, y: corners[2].y },
    { x: corners[3].x, y: corners[3].y },
  ]
    .map((point) => `${point.x * 100},${point.y * 100}`)
    .join(" ");

  return (
    <section data-testid="photo-editor" className="grid gap-3">
      <div
        ref={canvasRef}
        data-testid="corner-canvas"
        className="relative touch-none select-none overflow-hidden rounded-lg border border-border bg-foreground/5"
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- a blob URL (local file or private preview), which next/image cannot load #185 */}
        <img
          src={imageUrl}
          alt={t("previewAlt")}
          onLoad={handleImageLoad}
          draggable={false}
          className="block h-auto w-full"
          style={{
            filter: lightCorrection
              ? "contrast(1.06) saturate(1.05) brightness(1.03)"
              : undefined,
          }}
        />

        {shape === "rectangle" ? (
          <>
            <svg
              aria-hidden="true"
              viewBox="0 0 100 100"
              preserveAspectRatio="none"
              className="pointer-events-none absolute inset-0 size-full"
            >
              <polygon
                points={points}
                fill="var(--accent)"
                fillOpacity={0.12}
                stroke="var(--accent)"
                strokeWidth={1.5}
                vectorEffect="non-scaling-stroke"
              />
            </svg>

            {corners.map((corner, index) => (
              <div
                key={index}
                data-testid={`corner-handle-${index}`}
                role="slider"
                aria-label={t("cornerHandle", { index: index + 1 })}
                aria-valuenow={Math.round(corner.x * 100)}
                aria-valuemin={0}
                aria-valuemax={100}
                tabIndex={0}
                onPointerDown={quadPointerDown(index)}
                onPointerMove={quadPointerMove}
                onPointerUp={quadPointerUp}
                onPointerCancel={quadPointerUp}
                className="absolute z-10 flex size-8 -translate-x-1/2 -translate-y-1/2 touch-none items-center justify-center"
                style={{
                  left: `${corner.x * 100}%`,
                  top: `${corner.y * 100}%`,
                }}
              >
                <span className="size-4 rounded-full border-2 border-background bg-accent shadow" />
              </div>
            ))}

            {quadDrag && loupePoint ? (
              <div
                data-testid="corner-loupe"
                aria-hidden="true"
                className="pointer-events-none absolute z-20 size-24 rounded-full border-2 border-accent bg-background bg-no-repeat shadow-xl"
                style={{
                  left: `${loupePoint.x * 100}%`,
                  top: `${loupePoint.y * 100}%`,
                  transform: "translate(-50%, -140%)",
                  backgroundImage: `url(${imageUrl})`,
                  backgroundSize: `${quadDrag.bounds.width * 3}px ${
                    quadDrag.bounds.height * 3
                  }px`,
                  backgroundPosition: `${
                    -(loupePoint.x * quadDrag.bounds.width * 3 - 48)
                  }px ${-(loupePoint.y * quadDrag.bounds.height * 3 - 48)}px`,
                }}
              >
                <span className="absolute left-1/2 top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border border-accent" />
              </div>
            ) : null}
          </>
        ) : (
          <div
            data-testid="crop-frame"
            onPointerDown={cropPointerDownMove}
            onPointerMove={cropPointerMove}
            onPointerUp={cropPointerUp}
            onPointerCancel={cropPointerUp}
            className="absolute cursor-move touch-none border-2 border-accent bg-accent/15"
            style={{
              left: `${crop.x * 100}%`,
              top: `${crop.y * 100}%`,
              width: `${crop.width * 100}%`,
              height: `${crop.height * 100}%`,
            }}
          >
            {(["nw", "ne", "sw", "se"] as const).map((handle) => (
              <div
                key={handle}
                data-testid={`crop-handle-${handle}`}
                role="slider"
                aria-label={t("cropHandle", { corner: handle.toUpperCase() })}
                aria-valuenow={Math.round(crop.width * 100)}
                aria-valuemin={10}
                aria-valuemax={100}
                tabIndex={0}
                onPointerDown={cropPointerDownHandle(handle)}
                onPointerMove={cropPointerMove}
                onPointerUp={cropPointerUp}
                onPointerCancel={cropPointerUp}
                className="absolute size-7 touch-none rounded-full border-2 border-background bg-accent shadow"
                style={{
                  left:
                    handle === "nw" || handle === "sw"
                      ? "-0.875rem"
                      : "calc(100% - 0.875rem)",
                  top:
                    handle === "nw" || handle === "ne"
                      ? "-0.875rem"
                      : "calc(100% - 0.875rem)",
                }}
              />
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center justify-between gap-2 rounded-lg border border-border bg-background p-2">
        <div className="min-w-0">
          <p className="text-xs font-medium">{t("lightLabel")}</p>
          <p className="truncate text-[11px] text-foreground/60">
            {lightCorrection ? t("lightAfterHint") : t("lightBeforeHint")}
          </p>
        </div>
        <div
          role="group"
          aria-label={t("lightLabel")}
          className="flex shrink-0 rounded-md border border-border p-0.5"
        >
          <button
            type="button"
            aria-pressed={!lightCorrection}
            onClick={() => onLightCorrectionChange(false)}
            className={
              lightCorrection
                ? "rounded px-3 py-1 text-xs font-medium text-foreground/60"
                : "rounded bg-foreground/10 px-3 py-1 text-xs font-semibold"
            }
          >
            {t("lightBefore")}
          </button>
          <button
            type="button"
            aria-pressed={lightCorrection}
            onClick={() => onLightCorrectionChange(true)}
            className={
              lightCorrection
                ? "rounded bg-accent px-3 py-1 text-xs font-semibold text-accent-foreground"
                : "rounded px-3 py-1 text-xs font-medium text-foreground/60"
            }
          >
            {t("lightAfter")}
          </button>
        </div>
      </div>
    </section>
  );
}

