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

import { GroupPhotoFlow } from "@/features/photos/organisms/group-photo-flow";
import { resetMockState } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import messages from "../../messages/es.json";

const PRODUCTS_URL = "*/api/v1/staff/products/";
const PHOTO_UPLOAD_URL = /\/api\/v1\/staff\/photos\/?$/;
const PROCESSED_MEDIUM_URL =
  "https://media.example.test/stores/1/media/renditions/photo-801-800w-v1.webp";

const PRODUCT = {
  id: 13,
  name: "Frazada Invierno",
  slug: "frazada-invierno",
  category: { name: "Frazada", slug: "frazada" },
  needs_main_image: true,
  main_image: null,
};

function groupSubmission(
  id: number,
  overrides: Partial<PhotoSubmission> = {},
): PhotoSubmission {
  return {
    attempts: 0,
    corners: null,
    created_at: "2026-11-12T09:30:00Z",
    crop: null,
    failure_code: "",
    failure_message: "",
    id,
    kind: "group",
    light_correction: true,
    linked_product_ids: [],
    photographed_variant_id: null,
    pipeline_version: "2026-11-11.2",
    preview_url: `/api/v1/staff/photos/${id}/preview/`,
    redos: 0,
    redos_remaining: 0,
    result: null,
    status: "uploaded",
    target_product_id: null,
    updated_at: "2026-11-12T09:31:15Z",
    version: 1,
    ...overrides,
  };
}

function processedResult(id: number) {
  return {
    media_id: id + 1000,
    url: `https://media.example.test/stores/1/media/photo-${id}.jpg`,
    thumbnail_url: `https://media.example.test/stores/1/media/renditions/photo-${id}-320w-v1.webp`,
    medium_url: PROCESSED_MEDIUM_URL,
    width: 658,
    height: 823,
  };
}

function productsPage() {
  return {
    count: 1,
    next: null,
    previous: null,
    results: [PRODUCT],
  };
}

function renderFlow() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <NextIntlClientProvider locale="es" messages={messages}>
      <QueryClientProvider client={client}>
        <GroupPhotoFlow store="anime" />
      </QueryClientProvider>
    </NextIntlClientProvider>,
  );
}

async function startGroupPhoto() {
  fireEvent.change(await screen.findByLabelText("Tomar foto"), {
    target: {
      files: [new File(["photo"], "grupo.png", { type: "image/png" })],
    },
  });

  await screen.findByTestId("photo-editor");
  const editorImage = screen.getByAltText("Foto elegida sin procesar");
  Object.defineProperty(editorImage, "naturalWidth", {
    configurable: true,
    value: 800,
  });
  Object.defineProperty(editorImage, "naturalHeight", {
    configurable: true,
    value: 600,
  });
  fireEvent.load(editorImage);

  fireEvent.click(
    await screen.findByRole("checkbox", { name: "Elegir Frazada Invierno" }),
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

beforeEach(() => {
  resetMockState();
  URL.createObjectURL = vi.fn(() => "blob:group-photo");
  URL.revokeObjectURL = vi.fn();
});

describe("GroupPhotoFlow", () => {
  it("shows the processed group medium image once the photo is ready", async () => {
    server.use(
      http.get(PRODUCTS_URL, () => HttpResponse.json(productsPage())),
      http.post(PHOTO_UPLOAD_URL, () =>
        HttpResponse.json(groupSubmission(801), { status: 201 }),
      ),
      http.get("*/api/v1/staff/photos/801/", () =>
        HttpResponse.json(
          groupSubmission(801, {
            status: "ready",
            attempts: 1,
            result: processedResult(801),
            version: 3,
          }),
        ),
      ),
    );

    renderFlow();
    await startGroupPhoto();
    fireEvent.click(
      screen.getByRole("button", { name: "Enviar foto y continuar" }),
    );

    await waitFor(() =>
      expect(screen.getByTestId("group-photo-status")).toHaveAttribute(
        "data-state",
        "ready",
      ),
    );
    expect(
      screen.getByRole("img", {
        name: "Vista previa de la foto procesada",
      }),
    ).toHaveAttribute("src", PROCESSED_MEDIUM_URL);
  }, 15_000);

  it.each(["uploaded", "processing", "failed"] as const)(
    "keeps the original preview while the group photo is %s",
    async (status) => {
      server.use(
        http.get(PRODUCTS_URL, () => HttpResponse.json(productsPage())),
        http.post(PHOTO_UPLOAD_URL, () =>
          HttpResponse.json(groupSubmission(803), { status: 201 }),
        ),
        http.get("*/api/v1/staff/photos/:id/", ({ params }) =>
          HttpResponse.json(
            groupSubmission(Number(params.id), {
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
      await startGroupPhoto();
      fireEvent.click(
        screen.getByRole("button", { name: "Enviar foto y continuar" }),
      );

      await waitFor(() =>
        expect(screen.getByTestId("group-photo-status")).toHaveAttribute(
          "data-state",
          status,
        ),
      );
      const image = screen.getByRole("img", {
        name: "Vista previa de la foto procesada",
      });
      expect(image.getAttribute("src")).toMatch(/^blob:/);
      expect(image).not.toHaveAttribute("src", PROCESSED_MEDIUM_URL);
    },
    15_000,
  );
});
