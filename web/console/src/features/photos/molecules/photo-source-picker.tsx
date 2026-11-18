"use client";

import * as React from "react";
import { useTranslations } from "next-intl";
import { Camera, ImagePlus } from "lucide-react";

type PhotoSourcePickerProps = {
  localUrl: string | null;
  onSelect: (file: File) => void;
};

export function PhotoSourcePicker({
  localUrl,
  onSelect,
}: PhotoSourcePickerProps) {
  const t = useTranslations("Photos");
  const inputId = React.useId();

  return (
    <section className="grid gap-3 rounded-lg border border-border bg-background p-3">
      <input
        id={inputId}
        type="file"
        accept="image/*"
        capture="environment"
        aria-label={t("takePhoto")}
        className="sr-only"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) {
            onSelect(file);
          }
          event.target.value = "";
        }}
      />

      <label
        htmlFor={inputId}
        className="flex min-h-32 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-accent/50 bg-accent/5 px-4 py-6 text-center transition-colors hover:bg-accent/10 focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-accent"
      >
        <Camera aria-hidden="true" className="size-8 text-accent" />
        <span className="text-base font-semibold">{t("takePhoto")}</span>
        <span className="text-xs text-foreground/60">{t("cameraHint")}</span>
      </label>

      {localUrl ? (
        <div className="grid gap-2">
          <p className="text-xs font-medium text-foreground/70">
            {t("localPreview")}
          </p>
          <div className="overflow-hidden rounded-md border border-border bg-foreground/5">
            {/* eslint-disable-next-line @next/next/no-img-element -- a local blob URL, which next/image cannot load #185 */}
            <img
              src={localUrl}
              alt={t("previewAlt")}
              className="block h-auto w-full"
            />
          </div>
          <label
            htmlFor={inputId}
            className="inline-flex h-9 cursor-pointer items-center justify-center gap-2 rounded-md border border-border bg-background px-3 text-sm font-medium hover:bg-foreground/5"
          >
            <ImagePlus aria-hidden="true" className="size-4" />
            {t("changePhoto")}
          </label>
        </div>
      ) : null}
    </section>
  );
}
