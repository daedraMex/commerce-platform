"use client";

import * as React from "react";
import { useTranslations } from "next-intl";
import { Check, ImageOff, X } from "lucide-react";

import {
  useApiV1CatalogCategoriesList,
  useApiV1StaffProductsList,
} from "@commerce-platform/api-client";

import { Button } from "@/components/atoms/button";
import { cn } from "@/lib/utils";
import { useDebouncedState } from "../hooks/use-debounced-state";
import {
  photoCategoriesQueryKey,
  photoProductsQueryKey,
} from "../lib/queries";
import { toPhotoProduct } from "../types";

const SEARCH_DEBOUNCE_MS = 250;
const PAGE_SIZE = 100;

type GroupProductPickerProps = {
  store: string;
  selectedIds: readonly number[];
  onToggle: (productId: number) => void;
  onRemove: (productId: number) => void;
};

export function GroupProductPicker({
  store,
  selectedIds,
  onToggle,
  onRemove,
}: GroupProductPickerProps) {
  const t = useTranslations("Photos");

  const [searchInput, search, setSearchInput] = useDebouncedState(
    "",
    SEARCH_DEBOUNCE_MS,
  );
  const [category, setCategory] = React.useState("");
  const [onlyMissing, setOnlyMissing] = React.useState(false);

  const params = React.useMemo(
    () => ({
      search: search.trim() || undefined,
      category: category || undefined,
      needs_main_image: onlyMissing ? true : undefined,
      page_size: PAGE_SIZE,
    }),
    [search, category, onlyMissing],
  );

  const categories = useApiV1CatalogCategoriesList({
    query: { queryKey: photoCategoriesQueryKey(store) },
  });
  const products = useApiV1StaffProductsList(params, {
    query: { queryKey: photoProductsQueryKey(store, params) },
  });

  const results = React.useMemo(
    () => (products.data?.results ?? []).map(toPhotoProduct),
    [products.data],
  );
  const selected = React.useMemo(() => new Set(selectedIds), [selectedIds]);
  const nameById = React.useMemo(
    () => new Map(results.map((product) => [product.id, product.name])),
    [results],
  );

  return (
    <section
      data-testid="group-product-picker"
      data-selected-order={selectedIds.join(",")}
      aria-label={t("groupProductsLabel")}
      className="grid gap-3 rounded-lg border border-border bg-background p-3"
    >
      <div>
        <h3 className="text-sm font-semibold">{t("groupProductsHeading")}</h3>
        <p className="text-xs text-foreground/60">{t("groupProductsHint")}</p>
      </div>

      <div className="grid gap-2">
        <label className="grid gap-1">
          <span className="text-xs font-medium text-foreground/70">
            {t("searchLabel")}
          </span>
          <input
            type="search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder={t("searchPlaceholder")}
            className="h-9 w-full rounded-md border border-border bg-background px-3 text-sm"
          />
        </label>

        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <label className="grid gap-1">
            <span className="text-xs font-medium text-foreground/70">
              {t("categoryLabel")}
            </span>
            <select
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              disabled={categories.isPending}
              className="h-9 w-full rounded-md border border-border bg-background px-2 text-sm"
            >
              <option value="">{t("allCategories")}</option>
              {(categories.data ?? []).map((option) => (
                <option key={option.slug} value={option.slug}>
                  {option.name}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-2 self-end rounded-md border border-border px-3 py-2 text-sm">
            <input
              type="checkbox"
              checked={onlyMissing}
              onChange={(event) => setOnlyMissing(event.target.checked)}
              className="size-4 accent-[var(--accent)]"
            />
            <span>{t("onlyMissing")}</span>
          </label>
        </div>
      </div>

      <div>
        <p aria-live="polite" className="text-xs text-foreground/60">
          {t("groupSelectedCount", { count: selectedIds.length })}
        </p>
        {selectedIds.length > 0 ? (
          <ol
            aria-label={t("groupSelectedOrderLabel")}
            data-testid="group-selected-order"
            className="mt-2 flex flex-wrap gap-1"
          >
            {selectedIds.map((id, index) => {
              const name = nameById.get(id) ?? `#${id}`;
              return (
                <li key={id}>
                  <button
                    type="button"
                    onClick={() => onRemove(id)}
                    aria-label={t("groupRemoveSelected", { name })}
                    className="inline-flex items-center gap-1 rounded-full border border-accent/40 bg-accent/10 px-2 py-0.5 text-[11px] font-medium text-accent"
                  >
                    <span className="font-mono text-[10px] opacity-60">
                      {index + 1}
                    </span>
                    {name}
                    <X aria-hidden="true" className="size-3" />
                  </button>
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="mt-2 text-xs text-foreground/50">
            {t("groupSelectedEmpty")}
          </p>
        )}
      </div>

      {products.isPending ? (
        <p className="py-6 text-center text-sm text-foreground/60">
          {t("loading")}
        </p>
      ) : products.isError ? (
        <div className="rounded-lg border border-border p-3 text-center">
          <p className="text-sm text-foreground/70">{t("error")}</p>
          <Button
            variant="outline"
            size="sm"
            className="mt-2"
            onClick={() => products.refetch()}
          >
            {t("retry")}
          </Button>
        </div>
      ) : results.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border py-6 text-center text-sm text-foreground/60">
          {t("empty")}
        </p>
      ) : (
        <ul
          aria-label={t("groupResultsLabel")}
          className="grid grid-cols-2 gap-2 sm:grid-cols-3"
        >
          {results.map((product) => {
            const isSelected = selected.has(product.id);
            const image = product.main_image;
            return (
              <li key={product.id}>
                <label
                  data-testid={`group-product-${product.id}`}
                  className={cn(
                    "relative flex h-full cursor-pointer flex-col overflow-hidden rounded-lg border bg-background transition-colors",
                    isSelected
                      ? "border-accent ring-1 ring-accent/30"
                      : "border-border hover:bg-foreground/5",
                  )}
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => onToggle(product.id)}
                    aria-label={t("groupSelectProduct", {
                      name: product.name,
                    })}
                    className="absolute left-2 top-2 z-10 size-5 accent-[var(--accent)]"
                  />
                  <div className="relative aspect-square w-full overflow-hidden bg-foreground/5">
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
                    {isSelected ? (
                      <span className="absolute right-1 top-1 flex size-6 items-center justify-center rounded-full bg-accent text-accent-foreground shadow">
                        <Check aria-hidden="true" className="size-4" />
                      </span>
                    ) : null}
                  </div>
                  <div className="grid gap-0.5 p-2">
                    <span className="line-clamp-2 text-xs font-medium leading-tight">
                      {product.name}
                    </span>
                    <span className="truncate text-[11px] text-foreground/60">
                      {product.category.name}
                    </span>
                  </div>
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
