"use client";

import * as React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { GripVertical, ImageOff, Star } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  apiV1StaffPhotosApplyCreate,
  apiV1StaffPhotosRemoveCreate,
  apiV1StaffProductsImagesOrderUpdate,
  useApiV1StaffProductsImagesRetrieve,
  type CarouselImage,
} from "@commerce-platform/api-client";

import { Button } from "@/components/atoms/button";
import { cn } from "@/lib/utils";
import { photoCarouselQueryKey } from "../lib/queries";

type ProductCarouselPanelProps = {
  store: string;
  productId: number;
};

type CarouselData = {
  product_id: number;
  images: CarouselImage[];
};

type DragState = {
  id: number;
  startIds: number[];
  startImages: CarouselImage[];
  moved: boolean;
};

type CarouselAction = {
  kind: "apply" | "remove";
  submissionId: number;
};

function moveActive(
  images: CarouselImage[],
  fromId: number,
  toId: number,
): CarouselImage[] {
  const active = images.filter((image) => image.active);
  const inactive = images.filter((image) => !image.active);
  const from = active.findIndex((image) => image.id === fromId);
  const to = active.findIndex((image) => image.id === toId);
  if (from === -1 || to === -1 || from === to) {
    return images;
  }
  const next = [...active];
  const [moved] = next.splice(from, 1);
  if (!moved) {
    return images;
  }
  next.splice(to, 0, moved);
  return [...next, ...inactive];
}

export function ProductCarouselPanel({
  store,
  productId,
}: ProductCarouselPanelProps) {
  const t = useTranslations("Photos");
  const queryClient = useQueryClient();
  const queryKey = photoCarouselQueryKey(store, productId);

  const carousel = useApiV1StaffProductsImagesRetrieve(productId, {
    query: {
      queryKey,
      enabled: Number.isInteger(productId) && productId > 0,
    },
  });

  const [draggingId, setDraggingId] = React.useState<number | null>(null);
  const [reorderError, setReorderError] = React.useState<string | null>(null);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const dragRef = React.useRef<DragState | null>(null);

  const images = carousel.data?.images ?? [];

  const readImages = () =>
    queryClient.getQueryData<CarouselData>(queryKey)?.images ?? [];

  const reorder = useMutation({
    mutationFn: ({
      imageIds,
    }: {
      imageIds: number[];
      startImages: CarouselImage[];
    }) =>
      apiV1StaffProductsImagesOrderUpdate(productId, { image_ids: imageIds }),
    onSuccess: (response) => {
      queryClient.setQueryData<CarouselData>(queryKey, response);
    },
    onError: (_error, variables) => {
      queryClient.setQueryData<CarouselData>(queryKey, {
        product_id: productId,
        images: variables.startImages,
      });
      setReorderError(t("errorReorder"));
    },
  });

  const action = useMutation({
    mutationFn: ({ kind, submissionId }: CarouselAction) =>
      kind === "apply"
        ? apiV1StaffPhotosApplyCreate(submissionId)
        : apiV1StaffPhotosRemoveCreate(submissionId),
    onSuccess: () => {
      setActionError(null);
      void queryClient.invalidateQueries({ queryKey });
    },
    onError: () => setActionError(t("errorAction")),
  });

  const beginDrag = (
    event: React.PointerEvent<HTMLButtonElement>,
    id: number,
  ) => {
    if (reorder.isPending || action.isPending) {
      return;
    }
    if (event.pointerType === "mouse" && event.button !== 0) {
      return;
    }
    const startImages = readImages();
    const startIds = startImages
      .filter((image) => image.active)
      .map((image) => image.id)
      .filter((imageId): imageId is number => imageId !== null);
    dragRef.current = { id, startIds, startImages, moved: false };
    setDraggingId(id);
    setReorderError(null);
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  };

  const moveDrag = (event: React.PointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!drag) {
      return;
    }
    const target = document
      .elementFromPoint(event.clientX, event.clientY)
      ?.closest<HTMLElement>("[data-carousel-image-id]");
    const targetId = Number(target?.dataset.carouselImageId);
    if (!Number.isInteger(targetId) || targetId === drag.id) {
      return;
    }
    const current = readImages();
    const next = moveActive(current, drag.id, targetId);
    if (next === current) {
      return;
    }
    drag.moved = true;
    queryClient.setQueryData<CarouselData>(queryKey, {
      product_id: productId,
      images: next,
    });
  };

  const endDrag = () => {
    const drag = dragRef.current;
    dragRef.current = null;
    setDraggingId(null);
    if (!drag || !drag.moved) {
      return;
    }
    const imageIds = readImages()
      .filter((image) => image.active)
      .map((image) => image.id)
      .filter((imageId): imageId is number => imageId !== null);
    if (imageIds.length === 0) {
      return;
    }
    if (imageIds.join(",") === drag.startIds.join(",")) {
      return;
    }
    reorder.mutate({ imageIds, startImages: drag.startImages });
  };

  if (carousel.isPending) {
    return (
      <section
        aria-label={t("carouselLabel")}
        className="rounded-lg border border-border bg-background p-3 text-sm text-foreground/60"
      >
        {t("carouselLoading")}
      </section>
    );
  }

  if (carousel.isError) {
    return (
      <section
        aria-label={t("carouselLabel")}
        className="grid gap-2 rounded-lg border border-border bg-background p-3"
      >
        <p className="text-sm text-foreground/70">{t("carouselError")}</p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => carousel.refetch()}
        >
          {t("retry")}
        </Button>
      </section>
    );
  }

  const positionById = new Map(
    images
      .filter((image) => image.active && image.id !== null)
      .map((image, index) => [image.id as number, index + 1]),
  );

  return (
    <section
      aria-label={t("carouselLabel")}
      data-testid="product-carousel-panel"
      className="grid gap-3 rounded-lg border border-border bg-background p-3"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">{t("carouselHeading")}</h3>
          <p className="text-xs text-foreground/60">{t("carouselHint")}</p>
        </div>
        {reorder.isPending ? (
          <span className="text-xs text-foreground/40">
            {t("savingOrder")}
          </span>
        ) : null}
      </div>

      {reorderError ? (
        <p role="alert" className="text-xs font-medium text-foreground">
          {reorderError}
        </p>
      ) : null}
      {actionError ? (
        <p role="alert" className="text-xs font-medium text-foreground">
          {actionError}
        </p>
      ) : null}

      {images.length === 0 ? (
        <p className="rounded-md border border-dashed border-border py-6 text-center text-sm text-foreground/60">
          {t("carouselEmpty")}
        </p>
      ) : (
        <ol aria-label={t("carouselImagesLabel")} className="grid gap-2">
          {images.map((image) => {
            const isActive = image.active;
            const position =
              isActive && image.id !== null
                ? (positionById.get(image.id) ?? null)
                : null;
            const label = image.alt_text || t("carouselImageFallback");
            const busy = action.isPending || reorder.isPending;
            return (
              <li
                key={image.id ?? `pending-${image.media_id}`}
                data-testid="carousel-image"
                data-carousel-image-id={image.id ?? undefined}
                data-active={isActive ? "true" : "false"}
                data-position={position ?? undefined}
                className={cn(
                  "flex items-center gap-3 rounded-lg border-2 bg-background p-2 transition-colors",
                  isActive
                    ? "border-accent ring-1 ring-accent/30"
                    : "border-foreground/20 bg-foreground/[0.02]",
                  draggingId === image.id ? "opacity-60" : null,
                )}
              >
                <div className="relative size-16 shrink-0 overflow-hidden rounded-md bg-foreground/5">
                  {image.thumbnail_url ? (
                    // eslint-disable-next-line @next/next/no-img-element -- the thumbnail comes from the media bucket, which next/image cannot load (ADR-0026) #185
                    <img
                      src={image.thumbnail_url}
                      alt={label}
                      draggable={false}
                      className="size-full object-cover"
                    />
                  ) : (
                    <div className="flex size-full items-center justify-center text-foreground/40">
                      <ImageOff aria-hidden="true" className="size-5" />
                    </div>
                  )}
                </div>

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <p className="text-sm font-medium">
                      {position !== null
                        ? t("carouselImageNumber", { position })
                        : t("carouselInactiveImage")}
                    </p>
                    {isActive && position === 1 ? (
                      <span
                        data-testid="cover-badge"
                        className="inline-flex items-center gap-1 rounded-full bg-accent px-2 py-0.5 text-[11px] font-semibold text-accent-foreground"
                      >
                        <Star aria-hidden="true" className="size-3" />
                        {t("coverBadge")}
                      </span>
                    ) : null}
                    {!isActive ? (
                      <span className="rounded-full bg-foreground/10 px-2 py-0.5 text-[11px] font-medium text-foreground/60">
                        {t("inactiveBadge")}
                      </span>
                    ) : null}
                  </div>
                  <p className="truncate text-xs text-foreground/60">{label}</p>
                </div>

                <div className="flex shrink-0 flex-col items-end gap-1">
                  {isActive ? (
                    <>
                      <button
                        type="button"
                        aria-label={t("dragImage", {
                          position: position ?? 0,
                        })}
                        data-testid="carousel-drag-handle"
                        disabled={busy}
                        onPointerDown={(event) =>
                          image.id !== null && beginDrag(event, image.id)
                        }
                        onPointerMove={moveDrag}
                        onPointerUp={endDrag}
                        onPointerCancel={endDrag}
                        onLostPointerCapture={endDrag}
                        className="touch-none rounded-md border border-border p-1.5 text-foreground/60 disabled:opacity-40"
                      >
                        <GripVertical aria-hidden="true" className="size-4" />
                      </button>
                      {image.photo_submission_id !== null ? (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={busy}
                          onClick={() =>
                            action.mutate({
                              kind: "remove",
                              submissionId: image.photo_submission_id as number,
                            })
                          }
                        >
                          {t("removeCarouselImage")}
                        </Button>
                      ) : null}
                    </>
                  ) : image.photo_submission_id !== null ? (
                    <Button
                      size="sm"
                      disabled={busy}
                      onClick={() =>
                        action.mutate({
                          kind: "apply",
                          submissionId: image.photo_submission_id as number,
                        })
                      }
                    >
                      {t("approveCarouselImage")}
                    </Button>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {images.some((image) => !image.active) ? (
        <p className="text-xs text-foreground/50">{t("inactiveHint")}</p>
      ) : null}
    </section>
  );
}
