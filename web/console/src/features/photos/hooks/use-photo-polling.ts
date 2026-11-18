"use client";

import {
  apiV1StaffPhotosRetrieve,
  useApiV1StaffPhotosRetrieve,
  type PhotoSubmission,
} from "@commerce-platform/api-client";

import { isTerminalSubmission, nextPollDelay } from "../lib/polling";
import { photoSubmissionQueryKey } from "../lib/queries";

type UsePhotoPollingOptions = {
  store: string;
  submissionId: number | null;
  status: string | null | undefined;
  /** Processing attempts so far; a new attempt restarts the backoff. */
  attempt?: number;
  discarded?: boolean;
  onUpdate: (submission: PhotoSubmission) => void;
};

export function usePhotoPolling({
  store,
  submissionId,
  status,
  attempt = 0,
  discarded = false,
  onUpdate,
}: UsePhotoPollingOptions): void {
  const shouldPoll =
    submissionId !== null &&
    !!status &&
    !discarded &&
    !isTerminalSubmission({ status });
  const id = submissionId ?? 0;

  useApiV1StaffPhotosRetrieve(id, {
    query: {
      queryKey: photoSubmissionQueryKey(store, id, attempt),
      enabled: shouldPoll,
      retry: false,
      refetchOnWindowFocus: false,
      // The update is handed over where the response arrives, not in an effect (#166).
      queryFn: async ({ signal }) => {
        const submission = await apiV1StaffPhotosRetrieve(id, undefined, signal);
        onUpdate(submission);
        return submission;
      },
      refetchInterval: (query) => {
        const { data, dataUpdateCount, errorUpdateCount } = query.state;
        if (data && isTerminalSubmission(data)) {
          return false;
        }
        // A failed request keeps polling with the same backoff, as if still processing.
        const fetches = dataUpdateCount + errorUpdateCount;
        return (
          nextPollDelay(
            data?.status ?? "processing",
            fetches - 1,
            Boolean(data?.discarded_at),
          ) ?? false
        );
      },
    },
  });
}
