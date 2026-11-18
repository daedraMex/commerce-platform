export const POLL_DELAYS_MS = [1000, 2000, 4000, 8000] as const;

const TERMINAL_STATUSES = new Set(["ready", "failed", "discarded"]);

export function isTerminalStatus(status: string | null | undefined): boolean {
  return status !== null && status !== undefined
    ? TERMINAL_STATUSES.has(status)
    : false;
}

export function isTerminalSubmission(submission: {
  status: string | null | undefined;
  discarded_at?: string | null;
}): boolean {
  return Boolean(submission.discarded_at) || isTerminalStatus(submission.status);
}

export function nextPollDelay(
  status: string | null | undefined,
  attempt: number,
  discarded = false,
): number | null {
  if (discarded || !status || isTerminalStatus(status)) {
    return null;
  }

  const index = Math.min(
    Math.max(Math.trunc(attempt), 0),
    POLL_DELAYS_MS.length - 1,
  );
  return POLL_DELAYS_MS[index];
}
