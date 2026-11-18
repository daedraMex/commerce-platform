"use client";

import * as React from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { keepPreviousData } from "@tanstack/react-query";
import { Camera, Users } from "lucide-react";

import {
  useApiV1CatalogCategoriesList,
  useApiV1StaffProductsList,
} from "@commerce-platform/api-client";

import { Button } from "@/components/atoms/button";
import { useDebouncedValue } from "../hooks/use-debounced-value";
import {
  photoCategoriesQueryKey,
  photoProductsQueryKey,
} from "../lib/queries";
import { groupPhotoHref } from "../lib/routes";
import { ProductCard } from "../molecules/product-card";
import { toPhotoProduct } from "../types";

const SEARCH_DEBOUNCE_MS = 250;

type PhotosProductListProps = {
  store: string;
};

export function PhotosProductList({ store }: PhotosProductListProps) {
  const t = useTranslations("Photos");

  const [searchInput, setSearchInput] = React.useState("");
  const search = useDebouncedValue(searchInput, SEARCH_DEBOUNCE_MS);
  const [category, setCategory] = React.useState("");
  const [onlyMissing, setOnlyMissing] = React.useState(true);
  const [page, setPage] = React.useState(1);

  const params = React.useMemo(
    () => ({
      search: search.trim() || undefined,
      category: category || undefined,
      needs_main_image: onlyMissing ? true : undefined,
      page,
    }),
    [search, category, onlyMissing, page],
  );

  const categories = useApiV1CatalogCategoriesList({
    query: {
      queryKey: photoCategoriesQueryKey(store),
    },
  });
  const products = useApiV1StaffProductsList(params, {
    query: {
      queryKey: photoProductsQueryKey(store, params),
      placeholderData: keepPreviousData,
    },
  });

  const results = products.data?.results.map(toPhotoProduct) ?? [];
  const hasResults = results.length > 0;

  return (
    <main data-store={store} className="mx-auto w-full max-w-5xl p-3 sm:p-4">
      <div className="mb-3">
        <h2 className="text-xl font-semibold tracking-tight">
          {t("heading")}
        </h2>
        <p className="text-sm text-foreground/60">{t("subtitle")}</p>
      </div>

      <div className="mb-3 rounded-lg border border-accent/40 bg-accent/5 p-3">
        <Button asChild variant="outline" className="w-full sm:w-auto">
          <Link href={groupPhotoHref(store)}>
            <Users aria-hidden="true" />
            {t("groupAction")}
          </Link>
        </Button>
        <p className="mt-2 text-xs text-foreground/60">{t("groupHint")}</p>
      </div>

      <section
        aria-label={t("filtersLabel")}
        className="mb-3 grid gap-2 rounded-lg border border-border bg-background p-3"
      >
        <label className="grid gap-1">
          <span className="text-xs font-medium text-foreground/70">
            {t("searchLabel")}
          </span>
          <input
            type="search"
            value={searchInput}
            onChange={(event) => {
              setSearchInput(event.target.value);
              setPage(1);
            }}
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
              onChange={(event) => {
                setCategory(event.target.value);
                setPage(1);
              }}
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
              onChange={(event) => {
                setOnlyMissing(event.target.checked);
                setPage(1);
              }}
              className="size-4 accent-[var(--accent)]"
            />
            <span>{t("onlyMissing")}</span>
          </label>
        </div>
      </section>

      {products.isPending ? (
        <p className="py-8 text-center text-sm text-foreground/60">
          {t("loading")}
        </p>
      ) : products.isError ? (
        <div className="rounded-lg border border-border p-4 text-center">
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
      ) : (
        <>
          <div className="mb-2 flex items-center justify-between gap-2">
            <p aria-live="polite" className="text-xs text-foreground/60">
              {t("count", { count: products.data?.count ?? 0 })}
            </p>
            {products.isFetching ? (
              <span className="text-xs text-foreground/40">
                {t("loading")}
              </span>
            ) : null}
          </div>

          {hasResults ? (
            <ul aria-label={t("resultsLabel")} className="grid gap-2">
              {results.map((product) => (
                <li key={product.id}>
                  <ProductCard store={store} product={product} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="rounded-lg border border-dashed border-border py-8 text-center text-sm text-foreground/60">
              {t("empty")}
            </p>
          )}

          <nav
            aria-label={t("paginationLabel")}
            className="mt-3 flex items-center justify-between gap-2"
          >
            <Button
              variant="outline"
              size="sm"
              disabled={!products.data?.previous}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
            >
              {t("previous")}
            </Button>
            <span className="text-xs text-foreground/60">
              {t("page", { page })}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={!products.data?.next}
              onClick={() => setPage((current) => current + 1)}
            >
              {t("next")}
            </Button>
          </nav>
        </>
      )}

      <p className="mt-4 flex items-center justify-center gap-1 text-xs text-foreground/40">
        <Camera aria-hidden="true" className="size-3.5" />
        {t("individualHint")}
      </p>
    </main>
  );
}
