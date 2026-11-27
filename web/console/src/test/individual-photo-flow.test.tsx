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
import { CROP_ASPECT } from "@/features/photos/lib/geometry";
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

const CONTOUR_TARGET = {
  id: 16,
  name: "Almohada Hamburguesa",
  slug: "almohada-hamburguesa",
  category: { name: "Almohada", slug: "almohada" },
  needs_main_image: true,
  main_image: null,
};

const CONTOUR_DETAIL_URL = "*/api/v1/staff/products/16/";
const CONTOUR_CAROUSEL_URL = "*/api/v1/staff/products/16/images/";

type CapturedCrop = {
  x: number;
  y: number;
  width: number;
  height: number;
};

function contourSubmission(
  id: number,
  overrides: Partial<PhotoSubmission> = {},
): PhotoSubmission {
  return failedSubmission(id, {
    kind: "contour",
    target_product_id: CONTOUR_TARGET.id,
    corners: null,
    crop: null,
    status: "uploaded",
    failure_code: "",
    failure_message: "",
    version: 1,
    ...overrides,
  });
}

function cropOf(element: HTMLElement): CapturedCrop {
  return {
    x: Number(element.dataset.cropX),
    y: Number(element.dataset.cropY),
    width: Number(element.dataset.cropWidth),
    height: Number(element.dataset.cropHeight),
  };
}

function pixelRatio(
  crop: CapturedCrop,
  naturalWidth: number,
  naturalHeight: number,
): number {
  return (crop.width * naturalWidth) / (crop.height * naturalHeight);
}

function loadEditorImage(naturalWidth: number, naturalHeight: number) {
  const image = screen.getByAltText("Foto elegida sin procesar");
  Object.defineProperty(image, "naturalWidth", {
    configurable: true,
    value: naturalWidth,
  });
  Object.defineProperty(image, "naturalHeight", {
    configurable: true,
    value: naturalHeight,
  });
  fireEvent.load(image);
}

function mockCanvasBounds(width: number, height: number) {
  vi.spyOn(
    screen.getByTestId("corner-canvas"),
    "getBoundingClientRect",
  ).mockReturnValue({
    x: 0,
    y: 0,
    left: 0,
    top: 0,
    width,
    height,
    right: width,
    bottom: height,
    toJSON: () => ({}),
  } as DOMRect);
}

async function startContourPhoto() {
  fireEvent.change(await screen.findByLabelText("Tomar foto"), {
    target: {
      files: [new File(["photo"], "almohada.png", { type: "image/png" })],
    },
  });
  await screen.findByTestId("photo-editor");
}

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

describe("IndividualPhotoFlow contour crop", () => {
  it("keeps a new contour frame at 4:5 while moving and resizing, and uploads an exact 4:5 crop", async () => {
    const sentCrops: CapturedCrop[] = [];
    const originalAppend = FormData.prototype.append as (
      this: FormData,
      name: string,
      value: string | Blob,
      filename?: string,
    ) => void;
    vi.spyOn(FormData.prototype, "append").mockImplementation(function (
      this: FormData,
      name: string,
      value: string | Blob,
      filename?: string,
    ) {
      if (name === "crop" && typeof value === "string") {
        sentCrops.push(JSON.parse(value) as CapturedCrop);
      }
      return filename === undefined
        ? originalAppend.call(this, name, value)
        : originalAppend.call(this, name, value, filename);
    });

    server.use(
      http.get(CONTOUR_DETAIL_URL, () => HttpResponse.json(CONTOUR_TARGET)),
      http.get(CONTOUR_CAROUSEL_URL, () =>
        HttpResponse.json({ product_id: CONTOUR_TARGET.id, images: [] }),
      ),
      http.post(PHOTO_UPLOAD_URL, () =>
        HttpResponse.json(
          contourSubmission(910, {
            status: "ready",
            result: processedResult(910, FIRST_PROCESSED_MEDIUM_URL),
          }),
          { status: 201 },
        ),
      ),
    );

    renderFlow(CONTOUR_TARGET.id);
    await screen.findByTestId("photo-page-heading");
    await startContourPhoto();
    loadEditorImage(1000, 823);

    await waitFor(() =>
      expect(
        pixelRatio(cropOf(screen.getByTestId("crop-frame")), 1000, 823),
      ).toBeCloseTo(CROP_ASPECT, 6),
    );

    mockCanvasBounds(1000, 823);

    const resizeHandle = screen.getByTestId("crop-handle-se");
    fireEvent.pointerDown(resizeHandle, {
      pointerId: 1,
      clientX: 900,
      clientY: 823,
    });
    fireEvent.pointerMove(resizeHandle, {
      pointerId: 1,
      clientX: 700,
      clientY: 600,
    });
    fireEvent.pointerUp(resizeHandle, { pointerId: 1 });

    const resized = cropOf(screen.getByTestId("crop-frame"));
    expect(pixelRatio(resized, 1000, 823)).toBeCloseTo(CROP_ASPECT, 3);
    expect(resized.width).toBeLessThan(1);
    expect(resized.x).toBeGreaterThanOrEqual(0);
    expect(resized.x + resized.width).toBeLessThanOrEqual(1);
    expect(resized.y + resized.height).toBeLessThanOrEqual(1);

    const frame = screen.getByTestId("crop-frame");
    fireEvent.pointerDown(frame, {
      pointerId: 2,
      clientX: 500,
      clientY: 400,
    });
    fireEvent.pointerMove(frame, {
      pointerId: 2,
      clientX: 450,
      clientY: 350,
    });
    fireEvent.pointerUp(frame, { pointerId: 2 });

    const moved = cropOf(screen.getByTestId("crop-frame"));
    expect(pixelRatio(moved, 1000, 823)).toBeCloseTo(CROP_ASPECT, 3);
    expect(moved.x).toBeGreaterThanOrEqual(0);
    expect(moved.y).toBeGreaterThanOrEqual(0);

    fireEvent.click(screen.getByRole("button", { name: "Enviar foto" }));

    await waitFor(() => expect(sentCrops.length).toBeGreaterThan(0));
    const sent = sentCrops[0];
    expect(sent.width * 5).toBe(sent.height * 4);
    expect(sent.x).toBeGreaterThanOrEqual(0);
    expect(sent.y).toBeGreaterThanOrEqual(0);
    expect(sent.x + sent.width).toBeLessThanOrEqual(1000);
    expect(sent.y + sent.height).toBeLessThanOrEqual(823);
  }, 15_000);

  it("fits a stored contour crop with another ratio to 4:5 inside the image on redo", async () => {
    server.use(
      http.get(CONTOUR_DETAIL_URL, () => HttpResponse.json(CONTOUR_TARGET)),
      http.get(CONTOUR_CAROUSEL_URL, () =>
        HttpResponse.json({ product_id: CONTOUR_TARGET.id, images: [] }),
      ),
      http.post(PHOTO_UPLOAD_URL, () =>
        HttpResponse.json(
          contourSubmission(911, {
            status: "ready",
            crop: { x: 100, y: 100, width: 700, height: 400 },
            result: processedResult(911, FIRST_PROCESSED_MEDIUM_URL),
          }),
          { status: 201 },
        ),
      ),
    );

    renderFlow(CONTOUR_TARGET.id);
    await screen.findByTestId("photo-page-heading");
    await startContourPhoto();
    loadEditorImage(1000, 1000);
    fireEvent.click(screen.getByRole("button", { name: "Enviar foto" }));

    fireEvent.click(
      await screen.findByRole("button", { name: "Rehacer" }, { timeout: 5_000 }),
    );
    await screen.findByTestId("photo-editor");
    loadEditorImage(1000, 1000);

    await waitFor(() =>
      expect(
        pixelRatio(cropOf(screen.getByTestId("crop-frame")), 1000, 1000),
      ).toBeCloseTo(CROP_ASPECT, 6),
    );

    const restored = cropOf(screen.getByTestId("crop-frame"));
    expect(restored.x).toBeGreaterThanOrEqual(0);
    expect(restored.y).toBeGreaterThanOrEqual(0);
    expect(restored.x + restored.width).toBeLessThanOrEqual(1);
    expect(restored.y + restored.height).toBeLessThanOrEqual(1);
    expect(Math.round(restored.width * 1000) * 5).toBe(
      Math.round(restored.height * 1000) * 4,
    );
  }, 15_000);
});
