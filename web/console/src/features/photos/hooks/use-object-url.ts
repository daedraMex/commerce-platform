"use client";

import * as React from "react";

export function useObjectUrl(blob: Blob | null | undefined): string | null {
  const url = React.useMemo(
    () => (blob ? URL.createObjectURL(blob) : null),
    [blob],
  );

  React.useEffect(() => {
    return () => {
      if (url) {
        URL.revokeObjectURL(url);
      }
    };
  }, [url]);

  return url;
}
