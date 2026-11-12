"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/atoms/button";
import { CSRF_HEADER, CSRF_HEADER_VALUE } from "@/lib/auth/constants";

type SignInFormProps = {
  next?: string;
};

type SignInResponse = {
  redirectTo?: string;
};

type ProblemResponse = {
  code?: string;
};

export function SignInForm({ next }: SignInFormProps) {
  const router = useRouter();
  const t = useTranslations("SignIn");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPending(true);
    setError(null);

    try {
      const response = await fetch("/api/auth/sign-in", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          [CSRF_HEADER]: CSRF_HEADER_VALUE,
        },
        body: JSON.stringify({ email, password, next }),
      });

      if (!response.ok) {
        const problem = (await response.json()) as ProblemResponse;
        setError(messageFor(problem.code, t));
        return;
      }

      const payload = (await response.json()) as SignInResponse;
      router.replace(payload.redirectTo ?? "/");
      router.refresh();
    } catch {
      setError(t("networkError"));
    } finally {
      setPending(false);
    }
  };

  return (
    <form className="flex w-full flex-col gap-4" onSubmit={onSubmit}>
      <label className="flex flex-col gap-1 text-sm font-medium">
        {t("email")}
        <input
          className="h-10 rounded-md border border-border bg-background px-3 text-sm"
          type="email"
          name="email"
          autoComplete="username"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
        />
      </label>
      <label className="flex flex-col gap-1 text-sm font-medium">
        {t("password")}
        <input
          className="h-10 rounded-md border border-border bg-background px-3 text-sm"
          type="password"
          name="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
        />
      </label>
      {error ? (
        <p className="text-sm text-red-600" role="alert">
          {error}
        </p>
      ) : null}
      <Button type="submit" disabled={pending}>
        {pending ? t("submitting") : t("submit")}
      </Button>
    </form>
  );
}

function messageFor(
  code: string | undefined,
  t: ReturnType<typeof useTranslations>,
): string {
  if (code === "invalid_credentials") {
    return t("invalidCredentials");
  }
  if (code === "no_active_membership") {
    return t("noMembership");
  }
  return t("error");
}
