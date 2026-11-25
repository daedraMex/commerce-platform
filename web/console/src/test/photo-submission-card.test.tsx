import { cleanup, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { PhotoSubmission } from "@commerce-platform/api-client";

import { PhotoSubmissionCard } from "@/features/photos/organisms/photo-submission-card";
import messages from "../../messages/es.json";

function submission(
  overrides: Partial<PhotoSubmission> = {},
): PhotoSubmission {
  return {
    attempts: 1,
    corners: null,
    created_at: "2026-11-12T09:30:00Z",
    crop: null,
    failure_code: "",
    failure_message: "",
    id: 12,
    kind: "rectangle",
    light_correction: true,
    linked_product_ids: [],
    photographed_variant_id: null,
    pipeline_version: "2026-11-11.2",
    preview_url: "/api/v1/staff/photos/12/preview/",
    redos: 0,
    redos_remaining: 5,
    result: null,
    status: "ready",
    target_product_id: 13,
    updated_at: "2026-11-12T09:31:15Z",
    version: 4,
    ...overrides,
  };
}

function card(value: PhotoSubmission) {
  return (
    <NextIntlClientProvider locale="es" messages={messages}>
      <PhotoSubmissionCard
        submission={value}
        imageUrl="blob:preview-1"
        busyAction={null}
        errorMessage={null}
        onApply={vi.fn()}
        onRemove={vi.fn()}
        onRedo={vi.fn()}
        onRetry={vi.fn()}
        onDiscard={vi.fn()}
        onReplace={vi.fn()}
      />
    </NextIntlClientProvider>
  );
}

afterEach(() => {
  cleanup();
});

describe("PhotoSubmissionCard", () => {
  it("shows a grey pending border and En espera for a ready photo", () => {
    render(card(submission()));

    const container = screen.getByTestId("photo-submission-card");
    expect(container).toHaveAttribute("data-state", "pending");
    expect(container).toHaveClass("border-foreground/20");
    expect(container).not.toHaveClass("border-accent");
    expect(screen.getByTestId("photo-state-label")).toHaveTextContent(
      "En espera",
    );
    expect(screen.getByRole("button", { name: "Aprobar" })).toBeInTheDocument();
  });

  it("shows the accent border and En el carrusel for an approved photo", () => {
    render(card(submission({ applied_at: "2026-11-12T09:32:00Z" })));

    const container = screen.getByTestId("photo-submission-card");
    expect(container).toHaveAttribute("data-state", "approved");
    expect(container).toHaveClass("border-accent");
    expect(screen.getByTestId("photo-state-label")).toHaveTextContent(
      "En el carrusel",
    );
  });

  it("returns a removed photo to the grey En espera state without a reload", () => {
    const { rerender } = render(
      card(submission({ applied_at: "2026-11-12T09:32:00Z" })),
    );
    expect(screen.getByTestId("photo-state-label")).toHaveTextContent(
      "En el carrusel",
    );

    rerender(card(submission({ applied_at: null })));

    const container = screen.getByTestId("photo-submission-card");
    expect(container).toHaveAttribute("data-state", "pending");
    expect(container).not.toHaveClass("border-accent");
    expect(container).toHaveClass("border-foreground/20");
    expect(screen.getByTestId("photo-state-label")).toHaveTextContent(
      "En espera",
    );
  });

  it("offers retry and discard after a failure", () => {
    render(
      card(
        submission({
          status: "failed",
          failure_code: "quad_self_intersecting",
          failure_message: "The corners cross each other.",
        }),
      ),
    );

    expect(screen.getByTestId("photo-submission-card")).toHaveAttribute(
      "data-state",
      "failed",
    );
    expect(
      screen.getByRole("button", { name: "Reintentar" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Descartar" })).toBeInTheDocument();
  });

  it("offers redo on a failed photo and shows the remaining redos", () => {
    render(
      card(
        submission({
          status: "failed",
          failure_code: "quad_self_intersecting",
          redos: 2,
          redos_remaining: 3,
        }),
      ),
    );

    const redo = screen.getByRole("button", { name: "Rehacer" });
    expect(redo).toBeEnabled();
    expect(screen.getByTestId("redos-remaining")).toHaveTextContent(
      "Quedan 3 redos",
    );
  });

  it("shows the remaining redos while a ready photo can be redone", () => {
    render(card(submission({ redos: 4, redos_remaining: 1 })));

    expect(screen.getByRole("button", { name: "Rehacer" })).toBeEnabled();
    expect(screen.getByTestId("redos-remaining")).toHaveTextContent(
      "Queda 1 redo",
    );
  });

  it("disables redo and explains the photo must be replaced when no redos are left", () => {
    render(
      card(
        submission({
          status: "failed",
          redos: 5,
          redos_remaining: 0,
        }),
      ),
    );

    expect(screen.getByRole("button", { name: "Rehacer" })).toBeDisabled();
    expect(screen.getByTestId("redos-remaining")).toHaveTextContent(
      "No quedan redos. Descarta esta foto y toma una nueva.",
    );
  });

  it.each([
    ["applied", { applied_at: "2026-11-12T09:32:00Z" }],
    ["discarded", { discarded_at: "2026-11-12T09:32:00Z" }],
    ["uploaded", { status: "uploaded" }],
    ["processing", { status: "processing" }],
  ])("does not offer redo for a %s photo", (_label, overrides) => {
    render(card(submission(overrides)));

    expect(
      screen.queryByRole("button", { name: "Rehacer" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId("redos-remaining")).not.toBeInTheDocument();
  });
});
