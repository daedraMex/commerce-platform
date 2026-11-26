import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PhotoSubmission } from "@commerce-platform/api-client";

import { IndividualPhotoFlow } from "@/features/photos/organisms/individual-photo-flow";
import { resetMockState } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import messages from "../../messages/es.json";

const LIST_URL = "*/api/v1/staff/products/";
const DETAIL_URL = "*/api/v1/staff/products/130/";
const CAROUSEL_URL = "*/api/v1/staff/products/130/images/";
const FAILED_DETAIL_URL = "*/api/v1/staff/products/14/";
const FAILED_CAROUSEL_URL = "*/api/v1/staff/products/14/images/";
const PHOTO_UPLOAD_URL = /\/api\/v1\/staff\/photos\/?$/;
const FAILED_PHOTO_ID = 900;
const FAILED_PHOTO_URL = "*/api/v1/staff/photos/900/";

const TARGET = {
  id: 130,
  name: "Frazada Número Ciento Uno",
  slug: "frazada-numero-ciento-uno",
  category: { name: "Frazada", slug: "frazada" },
  needs_main_image: true,
  main_image: null,
};

const FAILED_TARGET = {
  ...TARGET,
  id: 14,
  name: "Frazada Fallida",
  slug: "frazada-fallida",
};

function failedSubmission(
  id: number,
  overrides: Partial<PhotoSubmission> = {},
): PhotoSubmission {
  return {
    attempts: 1,
    corners: [
      { x: 0.1, y: 0.1 },
      { x: 0.9, y: 0.1 },
      { x: 0.9, y: 0.9 },
      { x: 0.1, y: 0.9 },
    ],
    created_at: "2026-11-12T09:30:00Z",
    crop: null,
    failure_code: "quad_self_intersecting",
    failure_message: "The corners cross each other.",
    id,
    kind: "rectangle",
    light_correction: true,
    linked_product_ids: [],
    photographed_variant_id: null,
    pipeline_version: "2026-11-11.2",
    preview_url: `/api/v1/staff/photos/${id}/preview/`,
    redos: 0,
    redos_remaining: 5,
    result: null,
    status: "failed",
    target_product_id: 14,
    updated_at: "2026-11-12T09:31:15Z",
    version: 3,
    ...overrides,
  };
}

const FIRST_PROCESSED_MEDIUM_URL =
  "https://media.example.test/stores/1/media/renditions/photo-701-800w-v1.webp";
const REDONE_PROCESSED_MEDIUM_URL =
  "https://media.example.test/stores/1/media/renditions/photo-702-redo-800w-v1.webp";

function processedResult(id: number, mediumUrl: string) {
  return {
    media_id: id + 1000,
    url: `https://media.example.test/stores/1/media/photo-${id}.jpg`,
    thumbnail_url: `https://media.example.test/stores/1/media/renditions/photo-${id}-320w-v1.webp`,
    medium_url: mediumUrl,
    width: 658,
    height: 823,
  };
}

function readySubmission(
  id: number,
  mediumUrl: string,
  overrides: Partial<PhotoSubmission> = {},
): PhotoSubmission {
  return failedSubmission(id, {
    status: "ready",
    attempts: 1,
    failure_code: "",
    failure_message: "",
    result: processedResult(id, mediumUrl),
    version: 4,
    ...overrides,
  });
}

function firstPageWithoutTarget() {
  return Array.from({ length: 100 }, (_, index) => ({
    id: index + 1,
    name: `Frazada ${index + 1}`,
    slug: `frazada-${index + 1}`,
    category: { name: "Frazada", slug: "frazada" },
    needs_main_image: true,
    main_image: null,
  }));
}

function renderFlow(productId = TARGET.id) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <NextIntlClientProvider locale="es" messages={messages}>
      <QueryClientProvider client={client}>
        <IndividualPhotoFlow store="anime" productId={productId} />
      </QueryClientProvider>
    </NextIntlClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

beforeEach(() => {
  resetMockState();
  Object.defineProperty(HTMLElement.prototype, "setPointerCapture", {
    configurable: true,
    value: vi.fn(),
  });
  Object.defineProperty(HTMLElement.prototype, "releasePointerCapture", {
    configurable: true,
    value: vi.fn(),
  });
  Object.defineProperty(HTMLElement.prototype, "hasPointerCapture", {
    configurable: true,
    value: vi.fn(() => true),
  });
  URL.createObjectURL = vi.fn(() => "blob:individual-photo");
  URL.revokeObjectURL = vi.fn();
});

describe("IndividualPhotoFlow", () => {
  it("opens a product past the first 100 by loading it from the detail endpoint", async () => {
    server.use(
      http.get(LIST_URL, () =>
        HttpResponse.json({
          count: 101,
          next: "http://backend.test/api/v1/staff/products/?page=2",
          previous: null,
          results: firstPageWithoutTarget(),
        }),
      ),
      http.get(DETAIL_URL, () => HttpResponse.json(TARGET)),
      http.get(CAROUSEL_URL, () =>
        HttpResponse.json({ product_id: TARGET.id, images: [] }),
      ),
    );

    renderFlow();

    const heading = await screen.findByTestId("photo-page-heading");
    expect(heading).toHaveTextContent(TARGET.name);

    fireEvent.change(screen.getByLabelText("Tomar foto"), {
      target: {
        files: [new File(["photo"], "frazada.png", { type: "image/png" })],
      },
    });

    expect(await screen.findByTestId("photo-editor")).toBeInTheDocument();
  });

  it("redoes a failed photo with the new corners and returns it to processing", async () => {
    const captured: {
      redoBody: { corners?: Array<{ x: number; y: number }> } | null;
    } = { redoBody: null };
    server.use(
      http.get(FAILED_DETAIL_URL, () => HttpResponse.json(FAILED_TARGET)),
      http.get(FAILED_CAROUSEL_URL, () =>
        HttpResponse.json({ product_id: FAILED_TARGET.id, images: [] }),
      ),
      http.post(PHOTO_UPLOAD_URL, () =>
        HttpResponse.json(
          failedSubmission(FAILED_PHOTO_ID, {
            status: "uploaded",
            attempts: 0,
            failure_code: "",
            failure_message: "",
            version: 1,
          }),
          { status: 201 },
        ),
      ),
      http.get(FAILED_PHOTO_URL, () =>
        HttpResponse.json(failedSubmission(FAILED_PHOTO_ID)),
      ),
      http.post("*/api/v1/staff/photos/:id/redo", async ({ request, params }) => {
        captured.redoBody = (await request.json()) as typeof captured.redoBody;
        return HttpResponse.json(
          failedSubmission(Number(params.id), {
            status: "processing",
            redos: 1,
            redos_remaining: 4,
            failure_code: "",
            failure_message: "",
            version: 4,
          }),
        );
      }),
    );

    renderFlow(FAILED_TARGET.id);

    await screen.findByTestId("photo-page-heading");
    fireEvent.change(screen.getByLabelText("Tomar foto"), {
      target: {
        files: [new File(["photo"], "frazada.png", { type: "image/png" })],
      },
    });
    await screen.findByTestId("photo-editor");
    fireEvent.click(screen.getByRole("button", { name: "Enviar foto" }));

    const redo = await screen.findByRole(
      "button",
      { name: "Rehacer" },
      { timeout: 5_000 },
    );
    expect(screen.getByTestId("redos-remaining")).toHaveTextContent(
      "Puedes rehacerla 5 veces más",
    );

    fireEvent.click(redo);
    await screen.findByTestId("photo-editor");

    fireEvent.pointerDown(screen.getByTestId("corner-handle-0"), {
      pointerId: 1,
      clientX: 0,
      clientY: 0,
    });
    fireEvent.pointerUp(screen.getByTestId("corner-handle-0"), {
      pointerId: 1,
    });

    fireEvent.click(screen.getByRole("button", { name: "Rehacer foto" }));

    await waitFor(() => expect(captured.redoBody).not.toBeNull());
    expect(captured.redoBody?.corners?.[0]).toEqual({ x: 0, y: 0 });
    await waitFor(() =>
      expect(screen.getByTestId("photo-submission-card")).toHaveAttribute(
        "data-state",
        "processing",
      ),
    );
    expect(screen.getByTestId("photo-state-label")).toHaveTextContent(
      "Procesando…",
    );
  }, 15_000);

  it("shows the specific message when the redos are exhausted", async () => {
    server.use(
      http.get(FAILED_DETAIL_URL, () => HttpResponse.json(FAILED_TARGET)),
      http.get(FAILED_CAROUSEL_URL, () =>
        HttpResponse.json({ product_id: FAILED_TARGET.id, images: [] }),
      ),
      http.post(PHOTO_UPLOAD_URL, () =>
        HttpResponse.json(
          failedSubmission(FAILED_PHOTO_ID, {
            status: "uploaded",
            attempts: 0,
            failure_code: "",
            failure_message: "",
            version: 1,
          }),
          { status: 201 },
        ),
      ),
      http.get(FAILED_PHOTO_URL, () =>
        HttpResponse.json(failedSubmission(FAILED_PHOTO_ID)),
      ),
      http.post("*/api/v1/staff/photos/:id/redo", () =>
        HttpResponse.json(
          {
            code: "submission_redo_exhausted",
            detail: "This submission already used all its redos.",
            status: 409,
            title: "Conflict",
          },
          { status: 409 },
        ),
      ),
    );

    renderFlow(FAILED_TARGET.id);

    await screen.findByTestId("photo-page-heading");
    fireEvent.change(screen.getByLabelText("Tomar foto"), {
      target: {
        files: [new File(["photo"], "frazada.png", { type: "image/png" })],
      },
    });
    await screen.findByTestId("photo-editor");
    fireEvent.click(screen.getByRole("button", { name: "Enviar foto" }));

    const redo = await screen.findByRole(
      "button",
      { name: "Rehacer" },
      { timeout: 5_000 },
    );
    fireEvent.click(redo);
    await screen.findByTestId("photo-editor");

    fireEvent.click(screen.getByRole("button", { name: "Rehacer foto" }));

    expect(
      await screen.findByText(
        "Ya no puedes rehacer esta foto. Descártala y toma una nueva.",
      ),
    ).toBeInTheDocument();
  }, 15_000);

  it("shows the processed medium image once the photo is ready", async () => {
    server.use(
      http.get(LIST_URL, () =>
        HttpResponse.json({
          count: 1,
          next: null,
          previous: null,
          results: [TARGET],
        }),
      ),
      http.get(DETAIL_URL, () => HttpResponse.json(TARGET)),
      http.get(CAROUSEL_URL, () =>
        HttpResponse.json({ product_id: TARGET.id, images: [] }),
      ),
      http.post(PHOTO_UPLOAD_URL, () =>
        HttpResponse.json(
          failedSubmission(701, {
            status: "uploaded",
            attempts: 0,
            failure_code: "",
            failure_message: "",
            version: 1,
          }),
          { status: 201 },
        ),
      ),
      http.get("*/api/v1/staff/photos/701/", () =>
        HttpResponse.json(
          readySubmission(701, FIRST_PROCESSED_MEDIUM_URL),
        ),
      ),
    );

    renderFlow();
    await screen.findByTestId("photo-page-heading");
    fireEvent.change(screen.getByLabelText("Tomar foto"), {
      target: {
        files: [new File(["photo"], "frazada.png", { type: "image/png" })],
      },
    });
    await screen.findByTestId("photo-editor");
    fireEvent.click(screen.getByRole("button", { name: "Enviar foto" }));

    await waitFor(() =>
      expect(screen.getByTestId("photo-submission-card")).toHaveAttribute(
        "data-state",
        "pending",
      ),
    );
    expect(
      screen.getByRole("img", {
        name: "Vista previa de la foto procesada",
      }),
    ).toHaveAttribute("src", FIRST_PROCESSED_MEDIUM_URL);
  }, 15_000);

  it.each(["uploaded", "processing", "failed"] as const)(
    "keeps the original preview while the photo is %s",
    async (status) => {
      server.use(
        http.get(LIST_URL, () =>
          HttpResponse.json({
            count: 1,
            next: null,
            previous: null,
            results: [TARGET],
          }),
        ),
        http.get(DETAIL_URL, () => HttpResponse.json(TARGET)),
        http.get(CAROUSEL_URL, () =>
          HttpResponse.json({ product_id: TARGET.id, images: [] }),
        ),
        http.post(PHOTO_UPLOAD_URL, () =>
          HttpResponse.json(
            failedSubmission(703, {
              status: "uploaded",
              attempts: 0,
              failure_code: "",
              failure_message: "",
              version: 1,
            }),
            { status: 201 },
          ),
        ),
        http.get("*/api/v1/staff/photos/:id/", ({ params }) =>
          HttpResponse.json(
            failedSubmission(Number(params.id), {
              status,
              result: null,
              failure_code:
                status === "failed" ? "quad_self_intersecting" : "",
              failure_message:
                status === "failed" ? "The corners cross each other." : "",
            }),
          ),
        ),
      );

      renderFlow();
      await screen.findByTestId("photo-page-heading");
      fireEvent.change(screen.getByLabelText("Tomar foto"), {
        target: {
          files: [new File(["photo"], "frazada.png", { type: "image/png" })],
        },
      });
      await screen.findByTestId("photo-editor");
      fireEvent.click(screen.getByRole("button", { name: "Enviar foto" }));

      await waitFor(() =>
        expect(screen.getByTestId("photo-submission-card")).toHaveAttribute(
          "data-state",
          status === "failed" ? "failed" : "processing",
        ),
      );
      const image = screen.getByRole("img", {
        name: "Vista previa de la foto procesada",
      });
      expect(image.getAttribute("src")).toMatch(/^blob:/);
      expect(image).not.toHaveAttribute("src", FIRST_PROCESSED_MEDIUM_URL);
    },
    15_000,
  );

  it("shows the new processed result after a redo", async () => {
    let phase: "ready" | "redo" = "ready";
    server.use(
      http.get(LIST_URL, () =>
        HttpResponse.json({
          count: 1,
          next: null,
          previous: null,
          results: [TARGET],
        }),
      ),
      http.get(DETAIL_URL, () => HttpResponse.json(TARGET)),
      http.get(CAROUSEL_URL, () =>
        HttpResponse.json({ product_id: TARGET.id, images: [] }),
      ),
      http.post(PHOTO_UPLOAD_URL, () => {
        phase = "ready";
        return HttpResponse.json(
          failedSubmission(702, {
            status: "uploaded",
            attempts: 0,
            failure_code: "",
            failure_message: "",
            version: 1,
          }),
          { status: 201 },
        );
      }),
      http.get("*/api/v1/staff/photos/702/", () =>
        HttpResponse.json(
          readySubmission(
            702,
            phase === "ready"
              ? FIRST_PROCESSED_MEDIUM_URL
              : REDONE_PROCESSED_MEDIUM_URL,
          ),
        ),
      ),
      http.post("*/api/v1/staff/photos/702/redo", () => {
        phase = "redo";
        return HttpResponse.json(
          failedSubmission(702, {
            status: "processing",
            result: null,
            redos: 1,
            redos_remaining: 4,
            failure_code: "",
            failure_message: "",
            version: 5,
          }),
        );
      }),
    );

    renderFlow();
    await screen.findByTestId("photo-page-heading");
    fireEvent.change(screen.getByLabelText("Tomar foto"), {
      target: {
        files: [new File(["photo"], "frazada.png", { type: "image/png" })],
      },
    });
    await screen.findByTestId("photo-editor");
    fireEvent.click(screen.getByRole("button", { name: "Enviar foto" }));

    await waitFor(() =>
      expect(
        screen.getByRole("img", {
          name: "Vista previa de la foto procesada",
        }),
      ).toHaveAttribute("src", FIRST_PROCESSED_MEDIUM_URL),
    );

    fireEvent.click(screen.getByRole("button", { name: "Rehacer" }));
    await screen.findByTestId("photo-editor");
    fireEvent.click(screen.getByRole("button", { name: "Rehacer foto" }));

    await waitFor(() =>
      expect(
        screen.getByRole("img", {
          name: "Vista previa de la foto procesada",
        }),
      ).toHaveAttribute("src", REDONE_PROCESSED_MEDIUM_URL),
    );
  }, 15_000);
});
