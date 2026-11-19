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

export function isStoreDetailPath(pathname: string): boolean {
  const [first, , ...rest] = pathSegments(pathname);
  return Boolean(first && isStoreSegment(first) && rest.length > 0);
}

export function swapStoreInPath(pathname: string, store: string): string {
  const [path] = pathname.split(/[?#]/);
  const segments = pathSegments(path);
  const [first] = segments;

  if (!first || !isStoreSegment(first)) {
    return `/${store}`;
  }

  if (segments.length > 2) {
    return `/${store}/${segments[1]}`;
  }

  const section = segments[1] ? `/${segments[1]}` : "";
  const trailing = path.endsWith("/") ? "/" : "";
  return `/${store}${section}${trailing}`;
}

export function storeHref(store: string, segment: string): string {
  return segment.length > 0 ? `/${store}/${segment}` : `/${store}`;
}
