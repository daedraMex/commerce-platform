import { getTranslations } from "next-intl/server";

export default async function StoreHome({
  params,
}: {
  params: Promise<{ store: string }>;
}) {
  const { store } = await params;
  const t = await getTranslations("Placeholder");

  return (
    <main
      data-store={store}
      className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-4 p-6"
    >
      <h1 className="text-3xl font-semibold tracking-tight">{t("title")}</h1>
    </main>
  );
}
