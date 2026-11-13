import { getTranslations } from "next-intl/server";

export default async function StoreHome({
  params,
}: {
  params: Promise<{ store: string }>;
}) {
  const { store } = await params;
  const navigation = await getTranslations("Navigation");
  const t = await getTranslations("Home");

  return (
    <main
      data-store={store}
      className="mx-auto flex min-h-[60dvh] max-w-md flex-col items-center justify-center gap-4 p-6 text-center"
    >
      <h2 className="text-3xl font-semibold tracking-tight">
        {navigation("home")}
      </h2>
      <p className="text-sm text-foreground/60">{t("subtitle")}</p>
    </main>
  );
}
