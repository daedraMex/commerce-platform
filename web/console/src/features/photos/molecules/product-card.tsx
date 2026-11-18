"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { ImageOff } from "lucide-react";

import { individualPhotoHref } from "../lib/routes";
import type { PhotoProduct } from "../types";

type ProductCardProps = {
  store: string;
  product: PhotoProduct;
};

export function ProductCard({ store, product }: ProductCardProps) {
  const t = useTranslations("Photos");
  const image = product.main_image;

  return (
    <Link
      href={individualPhotoHref(store, product.id)}
      className="flex items-center gap-3 rounded-lg border border-border bg-background p-3 transition-colors hover:bg-foreground/5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      <div className="relative size-20 shrink-0 overflow-hidden rounded-md bg-foreground/5">
        {image ? (
          // eslint-disable-next-line @next/next/no-img-element -- the thumbnail is already sized by the media pipeline and its bucket host is not a next/image remote pattern #185
          <img
            src={image.thumbnail_url}
            alt={image.alt_text || product.name}
            width={image.width}
            height={image.height}
            className="size-full object-cover"
          />
        ) : (
          <div className="flex size-full flex-col items-center justify-center gap-1 text-foreground/40">
            <ImageOff aria-hidden="true" className="size-5" />
            <span className="px-1 text-center text-[10px] font-medium leading-tight">
              {t("noImage")}
            </span>
          </div>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">{product.name}</p>
        <p className="truncate text-xs text-foreground/60">
          {product.category.name}
        </p>
        <p
          className={
            image
              ? "mt-1 inline-block rounded bg-foreground/5 px-1.5 py-0.5 text-[11px] font-medium text-foreground/60"
              : "mt-1 inline-block rounded bg-accent/15 px-1.5 py-0.5 text-[11px] font-medium text-accent"
          }
        >
          {image ? t("hasMainImage") : t("needsMainImage")}
        </p>
      </div>
    </Link>
  );
}
