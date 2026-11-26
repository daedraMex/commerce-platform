"use client";

import * as React from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import {
  ArrowLeft,
  Camera,
  Check,
  LoaderCircle,
  Save,
  TriangleAlert,
} from "lucide-react";

import {
  apiV1StaffPhotosApplyCreate,
  apiV1StaffPhotosDiscardCreate,
  apiV1StaffPhotosLinksCreate,
  apiV1StaffPhotosRetryCreate,
  type PhotoSubmission,
} from "@commerce-platform/api-client";

import { Button } from "@/components/atoms/button";
import { storeHref } from "@/lib/store-path";
import { useGroupSelection } from "../hooks/use-group-selection";
import { useObjectUrl } from "../hooks/use-object-url";
import { usePhotoPolling } from "../hooks/use-photo-polling";
import { usePhotoPreview } from "../hooks/use-photo-preview";
import {
  cropAspectScale,
  cropForAspect,
  cropToPixels,
  DEFAULT_CROP,
  DEFAULT_QUAD,
  CROP_ASPECT,
  type NormalizedCrop,
  type PixelCrop,
} from "../lib/geometry";
import {
  reuseOrCreateUploadKey,
  type PhotoUploadKey,
} from "../lib/idempotency";
import { uploadPhoto } from "../lib/upload";
import { PhotoEditor } from "../molecules/photo-editor";
import { PhotoSourcePicker } from "../molecules/photo-source-picker";
import { GroupProductPicker } from "./group-product-picker";

type GroupPhotoFlowProps = {
  store: string;
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

export function GroupPhotoFlow({ store }: GroupPhotoFlowProps) {
  const t = useTranslations("Photos");

  const [stage, setStage] = React.useState<PhotoStage>("capture");
  const [file, setFile] = React.useState<File | null>(null);
  const [submission, setSubmission] = React.useState<PhotoSubmission | null>(
    null,
  );
  const [crop, setCrop] = React.useState<NormalizedCrop>(DEFAULT_CROP);
  const [lightCorrection, setLightCorrection] = React.useState(true);
  const [naturalSize, setNaturalSize] = React.useState({ width: 0, height: 0 });
  const [isUploading, setIsUploading] = React.useState(false);
  const [busyAction, setBusyAction] = React.useState<string | null>(null);
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const uploadKey = React.useRef<PhotoUploadKey | null>(null);
  const initializedCrop = React.useRef(false);
  const selection = useGroupSelection();

  const localUrl = useObjectUrl(file);
  const previewUrl = usePhotoPreview(
    submission?.id ?? null,
    submission !== null && !submission.discarded_at,
  );
  const statusImageUrl =
    submission?.result?.medium_url ?? previewUrl ?? localUrl;

  usePhotoPolling({
    store,
    submissionId: submission?.id ?? null,
    status: submission?.status,
    attempt: submission?.attempts ?? 0,
    discarded: Boolean(submission?.discarded_at),
    onUpdate: setSubmission,
  });

  const aspectScale = cropAspectScale(
    naturalSize.width,
    naturalSize.height,
    CROP_ASPECT,
  );
  const isApplied = Boolean(submission?.applied_at);
  const isDiscarded = Boolean(submission?.discarded_at);
  const isReady = submission?.status === "ready";
  const isFailed = submission?.status === "failed";
  const canRetry =
    isFailed && submission !== null && submission.attempts < 3 && !isDiscarded;

  const errorMessages: Record<string, string> = {
    idempotency_conflict: t("errorIdempotencyConflict"),
    submission_invalid_target: t("errorInvalidTarget"),
    invalid_image: t("errorInvalidImage"),
    too_large: t("errorTooLarge"),
    too_many_pixels: t("errorTooManyPixels"),
    submission_cannot_apply: t("errorCannotApply"),
    submission_cannot_change_links: t("errorCannotChangeLinks"),
    catalog_store_mismatch: t("errorStoreMismatch"),
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
    initializedCrop.current = false;
    setFile(null);
    setSubmission(null);
    setCrop(DEFAULT_CROP);
    setLightCorrection(true);
    setNaturalSize({ width: 0, height: 0 });
    setIsUploading(false);
    setBusyAction(null);
    setErrorMessage(null);
    setNotice(null);
    selection.clear();
    setStage("capture");
  };

  const selectFile = (nextFile: File) => {
    uploadKey.current = reuseOrCreateUploadKey(null, nextFile);
    initializedCrop.current = false;
    setFile(nextFile);
    setSubmission(null);
    setCrop(DEFAULT_CROP);
    setLightCorrection(true);
    setNaturalSize({ width: 0, height: 0 });
    setIsUploading(false);
    setErrorMessage(null);
    setNotice(null);
    setStage("edit");
  };

  const handleNaturalSize = (size: { width: number; height: number }) => {
    setNaturalSize(size);
    if (!initializedCrop.current && size.width > 0 && size.height > 0) {
      initializedCrop.current = true;
      setCrop(cropForAspect(size.width, size.height, CROP_ASPECT));
    }
  };

  const cropPayload = (): PixelCrop | undefined => {
    if (naturalSize.width <= 0 || naturalSize.height <= 0) {
      return undefined;
    }
    return cropToPixels(crop, naturalSize.width, naturalSize.height);
  };

  const submit = async () => {
    if (
      !file ||
      isUploading ||
      naturalSize.width <= 0 ||
      selection.count === 0
    ) {
      return;
    }

    setIsUploading(true);
    setErrorMessage(null);
    setNotice(null);

    try {
      const key = reuseOrCreateUploadKey(uploadKey.current, file);
      uploadKey.current = key;
      const next = await uploadPhoto({
        file,
        kind: "group",
        idempotencyKey: key.key,
        lightCorrection,
        crop: cropPayload(),
      });
      setSubmission(next);
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
    setNotice(null);
    try {
      const next = await call(submission.id);
      setSubmission(next);
    } catch (error) {
      setErrorMessage(describeError(error));
    } finally {
      setBusyAction(null);
    }
  };

  const applyToProducts = async () => {
    if (
      !submission ||
      busyAction !== null ||
      isApplied ||
      selection.count === 0
    ) {
      return;
    }

    setBusyAction("apply");
    setErrorMessage(null);
    setNotice(null);
    try {
      const next = await apiV1StaffPhotosApplyCreate(submission.id, {
        product_ids: selection.ids,
      });
      setSubmission(next);
      selection.reconcile(next.linked_product_ids);
    } catch (error) {
      setErrorMessage(describeError(error));
    } finally {
      setBusyAction(null);
    }
  };

  const saveLinks = async () => {
    if (!submission || busyAction !== null) {
      return;
    }

    setBusyAction("links");
    setErrorMessage(null);
    setNotice(null);
    try {
      const next = await apiV1StaffPhotosLinksCreate(submission.id, {
        product_ids: selection.ids,
      });
      setSubmission(next);
      selection.reconcile(next.linked_product_ids);
      setNotice(t("groupLinksSaved"));
    } catch (error) {
      setErrorMessage(describeError(error));
    } finally {
      setBusyAction(null);
    }
  };

  const toggleSelection = (productId: number) => {
    setNotice(null);
    selection.toggle(productId);
  };

  const removeSelection = (productId: number) => {
    setNotice(null);
    selection.remove(productId);
  };

  const stateLabel = isDiscarded
    ? t("discarded")
    : isApplied
      ? t("groupApplied")
      : submission?.status === "processing" || submission?.status === "uploaded"
        ? t("processing")
        : isFailed
          ? t("processingFailed")
          : t("waiting");

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

      <header className="mb-3">
        <p className="text-xs font-medium uppercase tracking-wide text-foreground/50">
          {t("groupEyebrow")}
        </p>
        <h2
          data-testid="photo-page-heading"
          className="text-xl font-semibold tracking-tight"
        >
          {t("groupHeading")}
        </h2>
        <p className="text-sm text-foreground/60">{t("groupSubtitle")}</p>
      </header>

      {stage === "capture" ? (
        <PhotoSourcePicker localUrl={localUrl} onSelect={selectFile} />
      ) : null}

      {stage === "edit" && localUrl ? (
        <div className="grid gap-3">
          <PhotoEditor
            imageUrl={localUrl}
            shape="group"
            corners={DEFAULT_QUAD}
            crop={crop}
            lightCorrection={lightCorrection}
            cropAspectScale={aspectScale}
            onCornersChange={() => undefined}
            onCropChange={setCrop}
            onLightCorrectionChange={setLightCorrection}
            onNaturalSize={handleNaturalSize}
          />

          <p className="rounded-md border border-border bg-foreground/[0.02] p-2 text-xs text-foreground/60">
            {t("groupCropHint")}
          </p>

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

          <GroupProductPicker
            store={store}
            selectedIds={selection.ids}
            onToggle={toggleSelection}
            onRemove={removeSelection}
          />

          <div className="grid gap-2">
            <Button
              onClick={submit}
              disabled={
                isUploading ||
                selection.count === 0 ||
                naturalSize.width <= 0
              }
            >
              {isUploading ? (
                <LoaderCircle aria-hidden="true" className="animate-spin" />
              ) : (
                <Check aria-hidden="true" />
              )}
              {isUploading ? t("uploading") : t("groupUpload")}
            </Button>
            {selection.count === 0 ? (
              <p className="text-center text-xs text-foreground/60">
                {t("groupSelectAtLeastOne")}
              </p>
            ) : null}
            <Button variant="outline" onClick={reset} disabled={isUploading}>
              {t("cancel")}
            </Button>
          </div>
        </div>
      ) : null}

      {stage === "status" && submission ? (
        <div className="grid gap-3">
          <section
            aria-label={t("photoStateLabel")}
            data-testid="group-photo-status"
            data-state={isDiscarded ? "discarded" : isApplied ? "applied" : submission.status}
            className="grid gap-3 rounded-lg border border-border bg-background p-3"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-sm font-semibold">{t("groupPreviewTitle")}</p>
                <p className="text-xs text-foreground/60">
                  {isDiscarded
                    ? t("discardedHint")
                    : isApplied
                      ? t("groupAppliedHint")
                      : isFailed
                        ? t("failedHint")
                        : isReady
                          ? t("groupReadyHint")
                          : t("processingHint")}
                </p>
              </div>
              <span
                data-testid="group-photo-state-label"
                className="shrink-0 rounded-full bg-foreground/10 px-2.5 py-1 text-[11px] font-semibold text-foreground/60"
              >
                {stateLabel}
              </span>
            </div>

            <div className="aspect-[4/5] overflow-hidden rounded-md border border-foreground/10 bg-foreground/5">
              {statusImageUrl ? (
                // eslint-disable-next-line @next/next/no-img-element -- a local or private-preview blob URL, which next/image cannot load #185
                <img
                  src={statusImageUrl}
                  alt={t("resultAlt")}
                  className="size-full object-cover"
                />
              ) : (
                <div className="flex size-full items-center justify-center text-sm text-foreground/50">
                  {t("noPreview")}
                </div>
              )}
            </div>

            {isFailed ? (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-md border border-foreground/20 bg-foreground/5 p-2 text-xs"
              >
                <TriangleAlert
                  aria-hidden="true"
                  className="mt-0.5 size-4 shrink-0 text-foreground/60"
                />
                <div>
                  <p className="font-medium">{t("processingFailed")}</p>
                  {submission.failure_message ? (
                    <p className="text-foreground/60">
                      {submission.failure_message}
                    </p>
                  ) : null}
                  {!canRetry ? (
                    <p className="mt-1 text-foreground/60">
                      {t("attemptsExhausted")}
                    </p>
                  ) : null}
                </div>
              </div>
            ) : null}

            {errorMessage ? (
              <p role="alert" className="text-xs font-medium text-foreground">
                {errorMessage}
              </p>
            ) : null}

            {notice ? (
              <p role="status" className="text-xs font-medium text-accent">
                {notice}
              </p>
            ) : null}

            <div className="flex flex-wrap gap-2">
              {canRetry ? (
                <Button
                  variant="outline"
                  onClick={() =>
                    runAction("retry", (id) =>
                      apiV1StaffPhotosRetryCreate(id),
                    )
                  }
                  disabled={busyAction !== null}
                >
                  {busyAction === "retry"
                    ? t("retrying")
                    : t("retryProcessing")}
                </Button>
              ) : null}

              {!isApplied && !isDiscarded && submission.status !== "processing" ? (
                <Button
                  variant="ghost"
                  onClick={() =>
                    runAction("discard", (id) =>
                      apiV1StaffPhotosDiscardCreate(id),
                    )
                  }
                  disabled={busyAction !== null}
                >
                  {busyAction === "discard"
                    ? t("discarding")
                    : t("discard")}
                </Button>
              ) : null}

              {isDiscarded ? (
                <Button variant="outline" onClick={reset}>
                  {t("takeAnother")}
                </Button>
              ) : null}
            </div>
          </section>

          {(isReady || isApplied) && !isDiscarded ? (
            <div className="grid gap-3">
              <GroupProductPicker
                store={store}
                selectedIds={selection.ids}
                onToggle={toggleSelection}
                onRemove={removeSelection}
              />

              {isApplied ? (
                <Button onClick={saveLinks} disabled={busyAction !== null}>
                  {busyAction === "links" ? (
                    <LoaderCircle
                      aria-hidden="true"
                      className="animate-spin"
                    />
                  ) : (
                    <Save aria-hidden="true" />
                  )}
                  {busyAction === "links"
                    ? t("groupSavingLinks")
                    : t("groupSaveLinks")}
                </Button>
              ) : (
                <Button
                  onClick={applyToProducts}
                  disabled={busyAction !== null || selection.count === 0}
                >
                  {busyAction === "apply" ? (
                    <LoaderCircle
                      aria-hidden="true"
                      className="animate-spin"
                    />
                  ) : (
                    <Check aria-hidden="true" />
                  )}
                  {busyAction === "apply"
                    ? t("applying")
                    : t("groupApply", { count: selection.count })}
                </Button>
              )}

              {!isApplied && selection.count === 0 ? (
                <p className="text-center text-xs text-foreground/60">
                  {t("groupSelectAtLeastOne")}
                </p>
              ) : null}

              <Button variant="ghost" onClick={reset}>
                <Camera aria-hidden="true" />
                {t("takeAnother")}
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
    </main>
  );
}
