import { getTranslations } from "next-intl/server";

import { SectionPlaceholder } from "@/components/templates/section-placeholder";

export default async function OrdersPage({
  params,
}: {
  params: Promise<{ store: string }>;
}) {
  const { store } = await params;
  const navigation = await getTranslations("Navigation");
  const t = await getTranslations("Sections");

  return (
    <SectionPlaceholder
      store={store}
      title={navigation("orders")}
      body={t("comingSoon")}
    />
  );
}
