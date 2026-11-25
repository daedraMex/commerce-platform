import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { IndividualPhotoFlow } from "@/features/photos/organisms/individual-photo-flow";
import { server } from "@/mocks/server";
import messages from "../../messages/es.json";

const LIST_URL = "*/api/v1/staff/products/";
const DETAIL_URL = "*/api/v1/staff/products/130/";
const CAROUSEL_URL = "*/api/v1/staff/products/130/images/";

const TARGET = {
  id: 130,
  name: "Frazada Número Ciento Uno",
  slug: "frazada-numero-ciento-uno",
  category: { name: "Frazada", slug: "frazada" },
  needs_main_image: true,
  main_image: null,
};

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
        <IndividualPhotoFlow store="anime" productId={TARGET.id} />
      </QueryClientProvider>
    </NextIntlClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

beforeEach(() => {
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
});
