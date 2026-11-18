"use client";

import * as React from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import {
  ArrowLeft,
  Camera,
  Check,
  LoaderCircle,
  TriangleAlert,
} from "lucide-react";

import {
  apiV1StaffPhotosApplyCreate,
  apiV1StaffPhotosDiscardCreate,
  apiV1StaffPhotosRemoveCreate,
  apiV1StaffPhotosRetryCreate,
  useApiV1CatalogCategoriesList,
  useApiV1StaffProductsList,
  type PhotoSubmission,
} from "@commerce-platform/api-client";

import { Button } from "@/components/atoms/button";
import { storeHref } from "@/lib/store-path";
import { useObjectUrl } from "../hooks/use-object-url";
import { usePhotoPolling } from "../hooks/use-photo-polling";
import { usePhotoPreview } from "../hooks/use-photo-preview";
import {
  DEFAULT_CROP,
  DEFAULT_QUAD,
  type NormalizedCrop,
  type NormalizedQuad,
  type PixelCrop,
} from "../lib/geometry";
import {
  reuseOrCreateUploadKey,
  type PhotoUploadKey,
} from "../lib/idempotency";
import {
  photoCategoriesQueryKey,
  photoProductsQueryKey,
} from "../lib/queries";
import { redoPhoto, uploadPhoto } from "../lib/upload";
import { PhotoEditor } from "../molecules/photo-editor";
import { PhotoSourcePicker } from "../molecules/photo-source-picker";
import { PhotoSubmissionCard } from "./photo-submission-card";

type IndividualPhotoFlowProps = {
  store: string;
  productId: number;
};

type PhotoStage = "capture" | "edit" | "status";

type ProblemBody = {
  code?: string;
  detail?: string;
};

function problemOf(error: unknown): ProblemBody | null {
  const data = (error as { response?: { data?: unknown } } | null)?.response
    ?.data;
  if (data && typeof data === "object") {
    return data as ProblemBody;
  }
  return null;
}

function toQuad(value: unknown): NormalizedQuad | null {
  if (!Array.isArray(value) || value.length !== 4) {
    return null;
  }

  const points = value.map((point) => {
    if (!point || typeof point !== "object") {
      return null;
    }
    const { x, y } = point as { x?: unknown; y?: unknown };
    return typeof x === "number" && typeof y === "number" ? { x, y } : null;
  });

  if (points.some((point) => point === null)) {
    return null;
  }
  return points as NormalizedQuad;
}

function toPixelCrop(value: unknown): PixelCrop | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const { x, y, width, height } = value as Record<string, unknown>;
  if (
    typeof x !== "number" ||
    typeof y !== "number" ||
    typeof width !== "number" ||
    typeof height !== "number"
  ) {
    return null;
  }
  return { x, y, width, height };
}

export function IndividualPhotoFlow({
  store,
  productId,
}: IndividualPhotoFlowProps) {
  const t = useTranslations("Photos");

  const products = useApiV1StaffProductsList(
    { page_size: 100 },
    { query: { queryKey: photoProductsQueryKey(store, { page_size: 100 }) } },
  );
  const categories = useApiV1CatalogCategoriesList({
    query: { queryKey: photoCategoriesQueryKey(store) },
  });
  const product = products.data?.results.find((item) => item.id === productId);
  const categoryShape = product
    ? categories.data?.find((category) => category.slug === product.category.slug)
        ?.shape
    : undefined;
  const shape: "rectangle" | "contour" =
    categoryShape === "contour" ? "contour" : "rectangle";

  const [stage, setStage] = React.useState<PhotoStage>("capture");
  const [file, setFile] = React.useState<File | null>(null);
  const [submission, setSubmission] = React.useState<PhotoSubmission | null>(
    null,
  );
  const [corners, setCorners] = React.useState<NormalizedQuad>(DEFAULT_QUAD);
  const [crop, setCrop] = React.useState<NormalizedCrop>(DEFAULT_CROP);
  const [initialPixelCrop, setInitialPixelCrop] =
    React.useState<PixelCrop | null>(null);
  const [lightCorrection, setLightCorrection] = React.useState(true);
  const [naturalSize, setNaturalSize] = React.useState({ width: 0, height: 0 });
  const [isRedoing, setIsRedoing] = React.useState(false);
  const [isUploading, setIsUploading] = React.useState(false);
  const [busyAction, setBusyAction] = React.useState<string | null>(null);
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);
  const uploadKey = React.useRef<PhotoUploadKey | null>(null);

  const localUrl = useObjectUrl(file);
  const previewUrl = usePhotoPreview(
    submission?.id ?? null,
    submission !== null && !submission.discarded_at,
  );
  const statusImageUrl = previewUrl ?? localUrl;
  const editorImageUrl = localUrl ?? previewUrl;

  usePhotoPolling({
    submissionId: submission?.id ?? null,
    status: submission?.status,
    discarded: Boolean(submission?.discarded_at),
    onUpdate: setSubmission,
  });

  const errorMessages: Record<string, string> = {
    idempotency_conflict: t("errorIdempotencyConflict"),
    submission_invalid_target: t("errorInvalidTarget"),
    invalid_image: t("errorInvalidImage"),
    too_large: t("errorTooLarge"),
    too_many_pixels: t("errorTooManyPixels"),
    submission_cannot_apply: t("errorCannotApply"),
    submission_cannot_remove: t("errorCannotRemove"),
    submission_cannot_redo: t("errorCannotRedo"),
    submission_cannot_start_processing: t("errorCannotRetry"),
    submission_attempts_exhausted: t("errorAttemptsExhausted"),
    submission_cannot_discard: t("errorCannotDiscard"),
  };

  const describeError = (error: unknown): string => {
    const problem = problemOf(error);
    if (problem?.code && errorMessages[problem.code]) {
      return errorMessages[problem.code];
    }
    return problem?.detail || t("errorAction");
  };

  const reset = () => {
    uploadKey.current = null;
    setFile(null);
    setSubmission(null);
    setCorners(DEFAULT_QUAD);
    setCrop(DEFAULT_CROP);
    setInitialPixelCrop(null);
    setLightCorrection(true);
    setIsRedoing(false);
    setIsUploading(false);
    setBusyAction(null);
    setErrorMessage(null);
    setStage("capture");
  };

  const selectFile = (nextFile: File) => {
    uploadKey.current = reuseOrCreateUploadKey(null, nextFile);
    setFile(nextFile);
    setSubmission(null);
    setCorners(DEFAULT_QUAD);
    setCrop(DEFAULT_CROP);
    setInitialPixelCrop(null);
    setLightCorrection(true);
    setIsRedoing(false);
    setErrorMessage(null);
    setStage("edit");
  };

  const cropPayload = (): PixelCrop | undefined => {
    if (shape !== "contour" || naturalSize.width <= 0) {
      return undefined;
    }
    return {
      x: Math.round(crop.x * naturalSize.width),
      y: Math.round(crop.y * naturalSize.height),
      width: Math.max(1, Math.round(crop.width * naturalSize.width)),
      height: Math.max(1, Math.round(crop.height * naturalSize.height)),
    };
  };

  const submitEditor = async () => {
    if (!file || isUploading) {
      return;
    }

    setIsUploading(true);
    setErrorMessage(null);

    try {
      if (isRedoing && submission) {
        const next = await redoPhoto({
          id: submission.id,
          corners: shape === "rectangle" ? corners : undefined,
          crop: shape === "contour" ? cropPayload() : undefined,
        });
        setSubmission(next);
        setIsRedoing(false);
      } else {
        const key = reuseOrCreateUploadKey(uploadKey.current, file);
        uploadKey.current = key;
        const next = await uploadPhoto({
          file,
          kind: shape,
          targetProductId: productId,
          idempotencyKey: key.key,
          lightCorrection,
          corners: shape === "rectangle" ? corners : undefined,
          crop: shape === "contour" ? cropPayload() : undefined,
        });
        setSubmission(next);
      }
      setStage("status");
    } catch (error) {
      setErrorMessage(describeError(error));
    } finally {
      setIsUploading(false);
    }
  };

  const runAction = async (
    action: string,
    call: (id: number) => Promise<PhotoSubmission>,
  ) => {
    if (!submission || busyAction !== null) {
      return;
    }

    setBusyAction(action);
    setErrorMessage(null);
    try {
      const next = await call(submission.id);
      setSubmission(next);
    } catch (error) {
      setErrorMessage(describeError(error));
    } finally {
      setBusyAction(null);
    }
  };

  const startRedo = () => {
    if (!submission || !file) {
      return;
    }

    const storedCorners = toQuad(submission.corners);
    const storedCrop = toPixelCrop(submission.crop);

    setCorners(storedCorners ?? DEFAULT_QUAD);
    setCrop(DEFAULT_CROP);
    setInitialPixelCrop(shape === "contour" ? storedCrop : null);
    setLightCorrection(submission.light_correction);
    setIsRedoing(true);
    setErrorMessage(null);
    setStage("edit");
  };

  const productQueryError = products.isError;
  const productMissing = products.data !== undefined && !product;

  return (
    <main data-store={store} className="mx-auto w-full max-w-md p-3 sm:p-4">
      <div className="mb-3">
        <Button variant="ghost" size="sm" asChild>
          <Link href={storeHref(store, "photos")}>
            <ArrowLeft aria-hidden="true" />
            {t("backToPhotos")}
          </Link>
        </Button>
      </div>

      {products.isPending || (categories.isPending && !categories.data) ? (
        <p className="py-8 text-center text-sm text-foreground/60">
          {t("loading")}
        </p>
      ) : productQueryError ? (
        <div className="rounded-lg border border-border p-4 text-center">
          <p className="text-sm text-foreground/70">{t("error")}</p>
          <Button
            variant="outline"
            size="sm"
            className="mt-2"
            onClick={() => products.refetch()}
          >
            {t("retry")}
          </Button>
        </div>
      ) : productMissing ? (
        <div className="rounded-lg border border-dashed border-border p-4 text-center">
          <p className="text-sm text-foreground/70">{t("productMissing")}</p>
        </div>
      ) : product ? (
        <>
          <header className="mb-3">
            <p className="text-xs font-medium uppercase tracking-wide text-foreground/50">
              {t("individualHeading")}
            </p>
            <h2
              data-testid="photo-page-heading"
              className="text-xl font-semibold tracking-tight"
            >
              {product.name}
            </h2>
            <p className="text-sm text-foreground/60">
              {t("individualSubtitle")}
            </p>
          </header>

          {stage === "capture" ? (
            <PhotoSourcePicker localUrl={localUrl} onSelect={selectFile} />
          ) : null}

          {stage === "edit" && editorImageUrl ? (
            <div className="grid gap-3">
              <PhotoEditor
                imageUrl={editorImageUrl}
                shape={shape}
                corners={corners}
                crop={crop}
                lightCorrection={lightCorrection}
                initialPixelCrop={initialPixelCrop}
                onCornersChange={setCorners}
                onCropChange={setCrop}
                onLightCorrectionChange={setLightCorrection}
                onNaturalSize={setNaturalSize}
              />

              {errorMessage ? (
                <div
                  role="alert"
                  className="flex items-start gap-2 rounded-md border border-foreground/20 bg-foreground/5 p-2 text-xs"
                >
                  <TriangleAlert
                    aria-hidden="true"
                    className="mt-0.5 size-4 shrink-0 text-foreground/60"
                  />
                  <p>{errorMessage}</p>
                </div>
              ) : null}

              <div className="grid gap-2">
                <Button onClick={submitEditor} disabled={isUploading}>
                  {isUploading ? (
                    <LoaderCircle aria-hidden="true" className="animate-spin" />
                  ) : (
                    <Check aria-hidden="true" />
                  )}
                  {isUploading
                    ? t("uploading")
                    : isRedoing
                      ? t("redoSubmit")
                      : t("upload")}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => {
                    if (isRedoing) {
                      setIsRedoing(false);
                      setStage("status");
                    } else {
                      reset();
                    }
                  }}
                  disabled={isUploading}
                >
                  {t("cancel")}
                </Button>
              </div>
            </div>
          ) : null}

          {stage === "status" && submission ? (
            <div className="grid gap-3">
              <PhotoSubmissionCard
                submission={submission}
                imageUrl={statusImageUrl}
                busyAction={busyAction}
                errorMessage={errorMessage}
                onApply={() =>
                  runAction("apply", (id) => apiV1StaffPhotosApplyCreate(id))
                }
                onRemove={() =>
                  runAction("remove", (id) => apiV1StaffPhotosRemoveCreate(id))
                }
                onRedo={startRedo}
                onRetry={() =>
                  runAction("retry", (id) => apiV1StaffPhotosRetryCreate(id))
                }
                onDiscard={() =>
                  runAction("discard", (id) =>
                    apiV1StaffPhotosDiscardCreate(id),
                  )
                }
                onReplace={reset}
              />
              <Button variant="ghost" onClick={reset}>
                <Camera aria-hidden="true" />
                {t("takeAnother")}
              </Button>
            </div>
          ) : null}
        </>
      ) : null}
    </main>
  );
}
