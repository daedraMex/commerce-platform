"use client";

import * as React from "react";

import {
  apiV1StaffPhotosRetrieve,
  type PhotoSubmission,
} from "@commerce-platform/api-client";

import { isTerminalSubmission, nextPollDelay } from "../lib/polling";

type UsePhotoPollingOptions = {
  submissionId: number | null;
  status: string | null | undefined;
  discarded?: boolean;
  onUpdate: (submission: PhotoSubmission) => void;
};

export function usePhotoPolling({
  submissionId,
  status,
  discarded = false,
  onUpdate,
}: UsePhotoPollingOptions): void {
  const onUpdateRef = React.useRef(onUpdate);

  React.useEffect(() => {
    onUpdateRef.current = onUpdate;
  }, [onUpdate]);

  const shouldPoll =
    submissionId !== null &&
    !!status &&
    !discarded &&
    !isTerminalSubmission({ status });

  React.useEffect(() => {
    if (!shouldPoll || submissionId === null) {
      return;
    }

    const id = submissionId;
    let cancelled = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    function schedule(delay: number | null) {
      if (delay === null || cancelled) {
        return;
      }
      timer = setTimeout(poll, delay);
    }

    async function poll() {
      try {
        const submission = await apiV1StaffPhotosRetrieve(id);
        if (cancelled) {
          return;
        }

        onUpdateRef.current(submission);
        if (isTerminalSubmission(submission)) {
          return;
        }

        const delay = nextPollDelay(
          submission.status,
          attempt,
          Boolean(submission.discarded_at),
        );
        attempt += 1;
        schedule(delay);
      } catch {
        if (cancelled) {
          return;
        }

        const delay = nextPollDelay("processing", attempt);
        attempt += 1;
        schedule(delay);
      }
    }

    void poll();

    return () => {
      cancelled = true;
      if (timer !== undefined) {
        clearTimeout(timer);
      }
    };
  }, [shouldPoll, submissionId]);
}
