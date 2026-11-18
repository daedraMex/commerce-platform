import { storeHref } from "@/lib/store-path";

export function individualPhotoHref(store: string, productId: number): string {
  return `${storeHref(store, "photos/new")}?product=${productId}`;
}

export function groupPhotoHref(store: string): string {
  return `${storeHref(store, "photos/new")}?kind=group`;
}
