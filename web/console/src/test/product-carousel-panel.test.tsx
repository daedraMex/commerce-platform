import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, delay, http } from "msw";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CarouselImage } from "@commerce-platform/api-client";

import { ProductCarouselPanel } from "@/features/photos/organisms/product-carousel-panel";
import { server } from "@/mocks/server";
import messages from "../../messages/es.json";

const CAROUSEL_URL = "*/api/v1/staff/products/12/images/";
const ORDER_URL = "*/api/v1/staff/products/12/images/order/";

function image(overrides: Partial<CarouselImage> = {}): CarouselImage {
  return {
    id: 101,
    media_id: 201,
    photo_submission_id: 1001,
    active: true,
    role: "main",
    position: 1,
    alt_text: "Primera foto",
    url: "https://media.example.test/stores/1/media/first.jpg",
    thumbnail_url:
      "https://media.example.test/stores/1/media/renditions/first-320w-v1.webp",
    medium_url:
      "https://media.example.test/stores/1/media/renditions/first-800w-v1.webp",
    width: 1200,
    height: 800,
    ...overrides,
  };
}

const IMAGES: CarouselImage[] = [
  image(),
  image({
    id: 102,
    media_id: 202,
    photo_submission_id: 1002,
    role: "gallery",
    position: 2,
    alt_text: "Segunda foto",
  }),
  image({
    id: 103,
    media_id: 203,
    photo_submission_id: 1003,
    active: false,
    role: "gallery",
    position: 3,
    alt_text: "Foto retirada",
  }),
  image({
    id: null,
    media_id: 204,
    photo_submission_id: 1004,
    active: false,
    role: null,
    position: null,
    alt_text: "Foto esperando aprobación",
  }),
];

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <NextIntlClientProvider locale="es" messages={messages}>
      <QueryClientProvider client={client}>
        <ProductCarouselPanel store="anime" productId={12} />
      </QueryClientProvider>
    </NextIntlClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

beforeEach(() => {
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
});

describe("ProductCarouselPanel", () => {
  it("shows the accent border and Portada on active images and grey borders on inactive ones", async () => {
    server.use(
      http.get(CAROUSEL_URL, () =>
        HttpResponse.json({ product_id: 12, images: IMAGES }),
      ),
    );

    renderPanel();

    const items = await screen.findAllByTestId("carousel-image");
    expect(items[0]).toHaveClass("border-accent");
    expect(items[0]).toContainElement(screen.getByTestId("cover-badge"));
    expect(screen.getByTestId("cover-badge")).toHaveTextContent("Portada");
    expect(items[1]).toHaveClass("border-accent");
    expect(items[2]).toHaveClass("border-foreground/20");
    expect(items[2]).toHaveTextContent("Inactiva");
    expect(items[3]).toHaveClass("border-foreground/20");
    expect(items[3]).toHaveTextContent("Publicar");
  });

  it("moves the image optimistically and rolls back with an error when saving fails", async () => {
    server.use(
      http.get(CAROUSEL_URL, () =>
        HttpResponse.json({ product_id: 12, images: IMAGES.slice(0, 2) }),
      ),
      http.put(ORDER_URL, async () => {
        await delay(100);
        return HttpResponse.json(
          {
            type: "about:blank",
            title: "Bad Request",
            status: 400,
            detail: "The order is invalid.",
            code: "catalog_invalid_image_order",
          },
          { status: 400, headers: { "content-type": "application/problem+json" } },
        );
      }),
    );

    renderPanel();

    const items = await screen.findAllByTestId("carousel-image");
    expect(items[0]).toHaveTextContent("Primera foto");
    const handles = screen.getAllByTestId("carousel-drag-handle");
    Object.defineProperty(document, "elementFromPoint", {
      configurable: true,
      value: vi.fn(() => items[0] ?? null),
    });

    fireEvent.pointerDown(handles[1] as HTMLElement, {
      pointerId: 1,
      pointerType: "touch",
      clientX: 0,
      clientY: 0,
    });
    fireEvent.pointerMove(handles[1] as HTMLElement, {
      pointerId: 1,
      pointerType: "touch",
      clientX: 0,
      clientY: 0,
    });
    fireEvent.pointerUp(handles[1] as HTMLElement, { pointerId: 1 });

    expect(screen.getAllByTestId("carousel-image")[0]).toHaveTextContent(
      "Segunda foto",
    );

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "No pudimos guardar el orden.",
      ),
    );
    expect(screen.getAllByTestId("carousel-image")[0]).toHaveTextContent(
      "Primera foto",
    );
  });

  it("ends the drag and sends the order when pointer capture is lost", async () => {
    let orderedIds: number[] | null = null;
    server.use(
      http.get(CAROUSEL_URL, () =>
        HttpResponse.json({ product_id: 12, images: IMAGES.slice(0, 2) }),
      ),
      http.put(ORDER_URL, async ({ request }) => {
        const body = (await request.json()) as { image_ids: number[] };
        orderedIds = body.image_ids;
        return HttpResponse.json({
          product_id: 12,
          images: [IMAGES[1], IMAGES[0]],
        });
      }),
    );

    renderPanel();

    const items = await screen.findAllByTestId("carousel-image");
    const handles = screen.getAllByTestId("carousel-drag-handle");
    Object.defineProperty(document, "elementFromPoint", {
      configurable: true,
      value: vi.fn(() => items[0] ?? null),
    });

    fireEvent.pointerDown(handles[1] as HTMLElement, {
      pointerId: 1,
      pointerType: "touch",
      clientX: 0,
      clientY: 0,
    });
    fireEvent.pointerMove(handles[1] as HTMLElement, {
      pointerId: 1,
      pointerType: "touch",
      clientX: 0,
      clientY: 0,
    });

    await waitFor(() =>
      expect(screen.getAllByTestId("carousel-image")[0]).toHaveTextContent(
        "Segunda foto",
      ),
    );

    fireEvent.lostPointerCapture(handles[1] as HTMLElement, { pointerId: 1 });

    await waitFor(() => expect(orderedIds).toEqual([102, 101]));
    await waitFor(() =>
      expect(screen.getAllByTestId("carousel-image")[0]).not.toHaveClass(
        "opacity-60",
      ),
    );
    expect(screen.getAllByTestId("carousel-image")[0]).toHaveTextContent(
      "Segunda foto",
    );
  });
});
