import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { Button } from "@/components/atoms/button";
import { PermissionGate } from "@/features/auth/organisms/permission-gate";
import { IndividualPhotoFlow } from "@/features/photos/organisms/individual-photo-flow";
import { storeHref } from "@/lib/store-path";

type NewPhotoPageProps = {
  params: Promise<{ store: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function NewPhotoPage({
  params,
  searchParams,
}: NewPhotoPageProps) {
  const { store } = await params;
  const query = await searchParams;
  const t = await getTranslations("Photos");
  const kind = firstValue(query.kind);
  const productId = Number(firstValue(query.product));

  let content: React.ReactNode;

  if (kind === "group") {
    content = (
      <main data-store={store} className="mx-auto w-full max-w-md p-3 sm:p-4">
        <h2 className="text-xl font-semibold tracking-tight">
          {t("groupHeading")}
        </h2>
        <p className="mt-2 rounded-lg border border-dashed border-border p-4 text-sm text-foreground/60">
          {t("groupComingSoon")}
        </p>
        <Button variant="outline" size="sm" className="mt-3" asChild>
          <Link href={storeHref(store, "photos")}>
            {t("backToPhotos")}
          </Link>
        </Button>
      </main>
    );
  } else if (Number.isInteger(productId) && productId > 0) {
    content = <IndividualPhotoFlow store={store} productId={productId} />;
  } else {
    content = (
      <main data-store={store} className="mx-auto w-full max-w-md p-3 sm:p-4">
        <p className="rounded-lg border border-dashed border-border p-4 text-sm text-foreground/60">
          {t("productMissing")}
        </p>
        <Button variant="outline" size="sm" className="mt-3" asChild>
          <Link href={storeHref(store, "photos")}>
            {t("backToPhotos")}
          </Link>
        </Button>
      </main>
    );
  }

  return (
    <PermissionGate store={store} permission="catalog.manage">
      {content}
    </PermissionGate>
  );
}
