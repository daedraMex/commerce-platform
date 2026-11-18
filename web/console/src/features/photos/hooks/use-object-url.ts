"use client";

import * as React from "react";

export function useObjectUrl(blob: Blob | null | undefined): string | null {
  const url = React.useMemo(
    () => (blob ? URL.createObjectURL(blob) : null),
    [blob],
  );

  // eslint-disable-next-line no-restricted-syntax -- revokes the blob URL, a browser resource outside React #185
  React.useEffect(() => {
    return () => {
      if (url) {
        URL.revokeObjectURL(url);
      }
    };
  }, [url]);

  return url;
}
