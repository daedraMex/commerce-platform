const RESERVED_SEGMENTS = new Set([
  "_next",
  "api",
  "favicon.ico",
  "sign-in",
]);

function pathSegments(pathname: string): string[] {
  return pathname.split(/[?#]/)[0].split("/").filter(Boolean);
}

export function isStoreSegment(segment: string): boolean {
  return segment.length > 0 && !RESERVED_SEGMENTS.has(segment);
}

export function storeSlugFromPathname(pathname: string): string | undefined {
  const [first] = pathSegments(pathname);
  return first && isStoreSegment(first) ? first : undefined;
}

export function swapStoreInPath(pathname: string, store: string): string {
  const segments = pathname.split("/");
  const [first] = pathSegments(pathname);

  if (!first || !isStoreSegment(first)) {
    return `/${store}`;
  }

  segments[1] = store;
  return segments.join("/");
}

export function storeHref(store: string, segment: string): string {
  return segment.length > 0 ? `/${store}/${segment}` : `/${store}`;
}
