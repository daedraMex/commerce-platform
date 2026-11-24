import {
  expect,
  test,
  type APIRequestContext,
  type Page,
  type TestInfo,
} from "@playwright/test";

import { CSRF_HEADER, CSRF_HEADER_VALUE } from "../src/lib/auth/constants";

const store = "home";
const apiURL = process.env.E2E_API_URL ?? "http://127.0.0.1:8000";
const email = process.env.E2E_STAFF_EMAIL ?? "e2e@example.com";
const password = process.env.E2E_STAFF_PASSWORD;

const GROUP_PRODUCTS = ["Notebooks Star Map", "Notebooks Forest Walk"];

type ProductSummary = { name: string; slug: string };

type StaffProduct = ProductSummary & {
  id: number;
  needs_main_image: boolean;
};

type ProductImage = { url: string; role: string; position: number };

type ProductDetail = { images: ProductImage[] };

type PhotoSubmission = {
  id: number;
  kind: string;
  target_product_id: number | null;
  crop: { x: number; y: number; width: number; height: number } | null;
  result: { url: string } | null;
  linked_product_ids: number[];
};

test.skip(!password, "E2E_STAFF_PASSWORD is required for the level-2 stack.");
test.describe.configure({ mode: "serial", timeout: 120_000 });

async function attachScreenshot(
  page: Page,
  testInfo: TestInfo,
  name: string,
) {
  await testInfo.attach(name, {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png",
  });
}

async function signIn(page: Page) {
  await page.goto("/home");
  await expect(page).toHaveURL(/\/sign-in\?next=%2Fhome$/);
  await page.getByLabel("Correo electrónico").fill(email);
  await page.getByLabel("Contraseña").fill(password ?? "");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page).toHaveURL(/\/home$/);
  await expect(page.getByRole("link", { name: "Fotos" })).toBeVisible();
}

async function openPhotos(page: Page) {
  await page.getByRole("link", { name: "Fotos" }).click();
  await expect(page).toHaveURL(/\/home\/photos$/);
  await expect(page.getByRole("heading", { name: "Fotos" })).toBeVisible();
}

async function pngFixture(page: Page, label: string): Promise<Buffer> {
  const base64 = await page.evaluate((text) => {
    const canvas = document.createElement("canvas");
    canvas.width = 800;
    canvas.height = 600;
    const context = canvas.getContext("2d");
    if (!context) {
      return "";
    }
    context.fillStyle = "#f4efe3";
    context.fillRect(0, 0, 800, 600);
    context.fillStyle = "#4f46e5";
    context.fillRect(80, 70, 640, 460);
    context.fillStyle = "#ffffff";
    context.font = "48px sans-serif";
    context.fillText(text, 250, 320);
    return canvas.toDataURL("image/png").split(",")[1] ?? "";
  }, label);

  if (!base64) {
    throw new Error("The browser could not render the PNG fixture.");
  }
  return Buffer.from(base64, "base64");
}

async function findPublicProduct(
  request: APIRequestContext,
  name: string,
): Promise<ProductSummary | null> {
  const response = await request.get(`${apiURL}/api/v1/catalog/products/`, {
    headers: { "X-Store": store },
    params: { search: name },
  });
  expect(response.ok()).toBeTruthy();
  const body = (await response.json()) as { results: ProductSummary[] };
  return body.results.find((product) => product.name === name) ?? null;
}

async function requirePublicProduct(
  request: APIRequestContext,
  name: string,
): Promise<ProductSummary> {
  const product = await findPublicProduct(request, name);
  if (!product) {
    throw new Error(`The seeded product "${name}" is missing from the public API.`);
  }
  return product;
}

async function publicProductDetail(
  request: APIRequestContext,
  slug: string,
): Promise<ProductDetail> {
  const response = await request.get(
    `${apiURL}/api/v1/catalog/products/${slug}/`,
    { headers: { "X-Store": store } },
  );
  expect(response.ok()).toBeTruthy();
  return (await response.json()) as ProductDetail;
}

async function findTargetProduct(page: Page): Promise<StaffProduct> {
  const body = await page.evaluate(
    async ({ storeSlug, csrfHeader, csrfValue }) => {
      const response = await fetch(
        "/api/backend/api/v1/staff/products/?page_size=100",
        {
          headers: {
            "X-Store": storeSlug,
            [csrfHeader]: csrfValue,
          },
        },
      );
      if (!response.ok) {
        throw new Error(
          `The staff products request failed with ${response.status}.`,
        );
      }
      return (await response.json()) as { results: StaffProduct[] };
    },
    {
      storeSlug: store,
      csrfHeader: CSRF_HEADER,
      csrfValue: CSRF_HEADER_VALUE,
    },
  );

  const product = body.results.find((item) => item.needs_main_image);
  if (!product) {
    throw new Error(
      "No product without a main image is available in the photo workflow.",
    );
  }
  return product;
}

async function submissionDetail(
  page: Page,
  id: number,
): Promise<PhotoSubmission> {
  return page.evaluate(
    async ({ submissionId, storeSlug, csrfHeader, csrfValue }) => {
      const response = await fetch(
        `/api/backend/api/v1/staff/photos/${submissionId}/`,
        {
          headers: {
            "X-Store": storeSlug,
            [csrfHeader]: csrfValue,
          },
        },
      );
      if (!response.ok) {
        throw new Error(
          `The submission request failed with ${response.status}.`,
        );
      }
      return (await response.json()) as PhotoSubmission;
    },
    {
      submissionId: id,
      storeSlug: store,
      csrfHeader: CSRF_HEADER,
      csrfValue: CSRF_HEADER_VALUE,
    },
  );
}

test("applies an individual photo as the product's main image", async ({
  page,
  request,
}, testInfo) => {
  await signIn(page);
  const target = await findTargetProduct(page);
  await openPhotos(page);

  const results = page.getByRole("list", { name: "Productos" });
  await page.getByLabel("Buscar").fill(target.name);
  const productLink = results.locator(
    `a[href$="/photos/new?product=${target.id}"]`,
  );
  await expect(productLink).toBeVisible();
  await attachScreenshot(page, testInfo, "photos-individual-list.png");

  await productLink.click();
  await expect(page).toHaveURL(
    new RegExp(`/home/photos/new\\?product=${target.id}$`),
  );
  await expect(page.getByTestId("photo-page-heading")).toHaveText(target.name);

  await page.getByLabel("Tomar foto").setInputFiles({
    name: "product.png",
    mimeType: "image/png",
    buffer: await pngFixture(page, "Producto"),
  });

  await expect(page.getByTestId("photo-editor")).toBeVisible();
  await expect(
    page.getByRole("group", { name: "Corrección de luz" }),
  ).toBeVisible();

  const uploadResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.status() === 201 &&
      response.url().includes("/api/backend/api/v1/staff/photos"),
  );
  await page.getByRole("button", { name: "Enviar foto" }).click();

  const created = (await (await uploadResponse).json()) as PhotoSubmission;
  expect(["rectangle", "contour"]).toContain(created.kind);
  expect(created.target_product_id).toEqual(expect.any(Number));

  await expect(page.getByTestId("photo-state-label")).toHaveText("En espera", {
    timeout: 90_000,
  });
  await attachScreenshot(page, testInfo, "photos-individual-ready.png");

  const ready = await submissionDetail(page, created.id);
  if (!ready.result) {
    throw new Error("The processed photo has no public result media.");
  }
  const resultURL = ready.result.url;

  const applyResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.status() === 200 &&
      response.url().includes(`/api/backend/api/v1/staff/photos/${created.id}/apply`),
  );
  await page.getByRole("button", { name: "Aprobar" }).click();
  await applyResponse;

  await expect(page.getByTestId("photo-state-label")).toHaveText(
    "En el carrusel",
  );
  await expect(page.getByTestId("photo-submission-card")).toHaveAttribute(
    "data-state",
    "approved",
  );
  await attachScreenshot(page, testInfo, "photos-individual-applied.png");

  const detail = await publicProductDetail(request, target.slug);
  expect(detail.images[0]).toMatchObject({
    url: resultURL,
    role: "main",
    position: 1,
  });
});

test("processes a group photo and links it to several products", async ({
  page,
  request,
}, testInfo) => {
  await signIn(page);
  await openPhotos(page);

  await page.getByRole("link", { name: "Foto grupal" }).click();
  await expect(page).toHaveURL(/\/home\/photos\/new\?kind=group$/);
  await expect(
    page.getByRole("heading", { name: "Foto grupal" }),
  ).toBeVisible();

  await page.getByLabel("Tomar foto").setInputFiles({
    name: "group.png",
    mimeType: "image/png",
    buffer: await pngFixture(page, "Grupo"),
  });

  await expect(page.getByTestId("photo-editor")).toBeVisible();
  await expect(page.getByTestId("group-product-picker")).toBeVisible();
  await expect(page.getByTestId("crop-frame")).toHaveAttribute(
    "data-shape",
    "group",
  );

  await page.getByLabel("Categoría").selectOption("demo-notebooks");
  for (const name of GROUP_PRODUCTS) {
    const checkbox = page.getByRole("checkbox", {
      name: `Elegir ${name}`,
    });
    await expect(checkbox).toBeVisible();
    await checkbox.check();
  }

  const picker = page.getByTestId("group-product-picker");
  const selectedOrder = await picker.getAttribute("data-selected-order");
  expect(selectedOrder?.split(",")).toHaveLength(2);
  await attachScreenshot(page, testInfo, "photos-group-selection.png");

  const uploadResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.status() === 201 &&
      response.url().includes("/api/backend/api/v1/staff/photos"),
  );
  await page.getByRole("button", { name: "Enviar foto y continuar" }).click();

  const created = (await (await uploadResponse).json()) as PhotoSubmission;
  expect(created.kind).toBe("group");
  expect(created.target_product_id).toBeNull();
  if (!created.crop) {
    throw new Error("The group upload did not include its crop.");
  }
  expect(created.crop.width / created.crop.height).toBeCloseTo(0.8, 2);

  await expect(page.getByTestId("group-photo-state-label")).toHaveText(
    "En espera",
    { timeout: 90_000 },
  );
  await attachScreenshot(page, testInfo, "photos-group-ready.png");

  const ready = await submissionDetail(page, created.id);
  if (!ready.result) {
    throw new Error("The processed group photo has no public result media.");
  }
  const resultURL = ready.result.url;

  const applyResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.status() === 200 &&
      response.url().includes(`/api/backend/api/v1/staff/photos/${created.id}/apply`),
  );
  await page.getByRole("button", { name: "Aplicar a 2 productos" }).click();
  const applied = (await (await applyResponse).json()) as PhotoSubmission;
  expect(applied.linked_product_ids).toHaveLength(2);

  await expect(page.getByTestId("group-photo-state-label")).toHaveText(
    "Aplicada",
  );
  await expect(page.getByTestId("group-photo-status")).toHaveAttribute(
    "data-state",
    "applied",
  );
  await attachScreenshot(page, testInfo, "photos-group-applied.png");

  for (const name of GROUP_PRODUCTS) {
    const product = await requirePublicProduct(request, name);
    const detail = await publicProductDetail(request, product.slug);
    expect(detail.images.map((image) => image.url)).toContain(resultURL);
  }
});
