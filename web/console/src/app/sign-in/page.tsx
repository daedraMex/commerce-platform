import { getTranslations } from "next-intl/server";

import { SignInForm } from "@/features/auth/organisms/sign-in-form";

export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string | string[] }>;
}) {
  const params = await searchParams;
  const next = Array.isArray(params.next) ? params.next[0] : params.next;
  const t = await getTranslations("SignIn");

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-6 p-6">
      <div className="space-y-1">
        <h1 className="text-3xl font-semibold tracking-tight">{t("title")}</h1>
        <p className="text-sm text-foreground/60">{t("subtitle")}</p>
      </div>
      <SignInForm next={next} />
    </main>
  );
}
