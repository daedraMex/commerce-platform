"use client";

import { useTranslations } from "next-intl";
import { AlertTriangle, RotateCcw } from "lucide-react";

import type { PhotoSubmission } from "@commerce-platform/api-client";

import { Button } from "@/components/atoms/button";
import { cn } from "@/lib/utils";

export type PhotoCardState =
  | "approved"
  | "pending"
  | "processing"
  | "failed"
  | "discarded";

export function photoCardState(submission: PhotoSubmission): PhotoCardState {
  if (submission.discarded_at) {
    return "discarded";
  }
  if (submission.applied_at) {
    return "approved";
  }
  if (submission.status === "ready") {
    return "pending";
  }
  if (submission.status === "failed") {
    return "failed";
  }
  return "processing";
}

type PhotoSubmissionCardProps = {
  submission: PhotoSubmission;
  imageUrl: string | null;
  busyAction: string | null;
  errorMessage: string | null;
  onApply: () => void;
  onRemove: () => void;
  onRedo: () => void;
  onRetry: () => void;
  onDiscard: () => void;
  onReplace: () => void;
};

export function PhotoSubmissionCard({
  submission,
  imageUrl,
  busyAction,
  errorMessage,
  onApply,
  onRemove,
  onRedo,
  onRetry,
  onDiscard,
  onReplace,
}: PhotoSubmissionCardProps) {
  const t = useTranslations("Photos");
  const state = photoCardState(submission);
  const busy = busyAction !== null;
  const canRetry = state === "failed" && submission.attempts < 3;
  const canRedo = state === "pending" || state === "failed";
  const redosExhausted = submission.redos_remaining <= 0;

  const labels: Record<PhotoCardState, string> = {
    approved: t("inCarousel"),
    pending: t("waiting"),
    processing: t("processing"),
    failed: t("processingFailed"),
    discarded: t("discarded"),
  };

  return (
    <section
      aria-label={t("photoStateLabel")}
      data-testid="photo-submission-card"
      data-state={state}
      className={cn(
        "grid gap-3 rounded-lg border-2 bg-background p-3 transition-colors",
        state === "approved"
          ? "border-accent ring-1 ring-accent/30"
          : "border-foreground/20 bg-foreground/[0.02]",
        state === "discarded" ? "opacity-70" : null,
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold">
            {state === "approved"
              ? t("photoApprovedTitle")
              : t("photoPreviewTitle")}
          </p>
          <p className="text-xs text-foreground/60">
            {state === "pending"
              ? t("waitingHint")
              : state === "approved"
                ? t("inCarouselHint")
                : state === "failed"
                  ? t("failedHint")
                  : state === "discarded"
                    ? t("discardedHint")
                    : t("processingHint")}
          </p>
        </div>
        <span
          data-testid="photo-state-label"
          className={cn(
            "shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold",
            state === "approved"
              ? "bg-accent text-accent-foreground"
              : "bg-foreground/10 text-foreground/60",
          )}
        >
          {labels[state]}
        </span>
      </div>

      <div className="overflow-hidden rounded-md border border-foreground/10 bg-foreground/5">
        {imageUrl ? (
          // eslint-disable-next-line @next/next/no-img-element -- a local or private-preview blob URL, which next/image cannot load #185
          <img
            src={imageUrl}
            alt={t("resultAlt")}
            className="block h-auto w-full"
          />
        ) : (
          <div className="flex min-h-40 items-center justify-center text-sm text-foreground/50">
            {t("noPreview")}
          </div>
        )}
      </div>

      {state === "failed" ? (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-md border border-foreground/20 bg-foreground/5 p-2 text-xs"
        >
          <AlertTriangle
            aria-hidden="true"
            className="mt-0.5 size-4 shrink-0 text-foreground/60"
          />
          <div>
            <p className="font-medium">{t("processingFailed")}</p>
            {submission.failure_message ? (
              <p className="text-foreground/60">{submission.failure_message}</p>
            ) : null}
            {submission.failure_code ? (
              <p className="mt-0.5 font-mono text-[10px] text-foreground/40">
                {submission.failure_code}
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

      {canRedo ? (
        <p
          data-testid="redos-remaining"
          className="text-xs text-foreground/60"
        >
          {redosExhausted
            ? t("redosExhaustedHint")
            : t("redosRemaining", { count: submission.redos_remaining })}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {state === "pending" ? (
          <Button onClick={onApply} disabled={busy}>
            {busyAction === "apply" ? t("applying") : t("approve")}
          </Button>
        ) : null}

        {state === "approved" ? (
          <Button variant="outline" onClick={onRemove} disabled={busy}>
            {busyAction === "remove" ? t("removing") : t("remove")}
          </Button>
        ) : null}

        {canRedo ? (
          <Button
            variant="outline"
            onClick={onRedo}
            disabled={busy || redosExhausted}
          >
            <RotateCcw aria-hidden="true" />
            {t("redo")}
          </Button>
        ) : null}

        {canRetry ? (
          <Button variant="outline" onClick={onRetry} disabled={busy}>
            {busyAction === "retry" ? t("retrying") : t("retryProcessing")}
          </Button>
        ) : null}

        {state === "pending" ||
        state === "failed" ||
        state === "processing" ? (
          <Button variant="ghost" onClick={onDiscard} disabled={busy}>
            {busyAction === "discard" ? t("discarding") : t("discard")}
          </Button>
        ) : null}

        {state === "discarded" ? (
          <Button variant="outline" onClick={onReplace} disabled={busy}>
            {t("takeAnother")}
          </Button>
        ) : null}
      </div>
    </section>
  );
}
