import { expect, test } from "@playwright/test";

import {
  LIMITED_EMAIL,
  VALID_EMAIL,
  VALID_PASSWORD,
} from "../src/mocks/handlers";

test.describe.configure({ mode: "serial" });

async function attachScreenshot(
  page: import("@playwright/test").Page,
  testInfo: import("@playwright/test").TestInfo,
  name: string,
) {
  await testInfo.attach(name, {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png",
  });
}

async function signIn(
  page: import("@playwright/test").Page,
  email = VALID_EMAIL,
) {
  await page.goto("/sign-in?next=%2Fanime");
  await page.getByLabel("Correo electrónico").fill(email);
  await page.getByLabel("Contraseña").fill(VALID_PASSWORD);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page).toHaveURL(/\/anime$/);
}

async function openPhotos(page: import("@playwright/test").Page) {
  await page.getByRole("link", { name: "Fotos" }).click();
  await expect(page).toHaveURL(/\/anime\/photos$/);
  await expect(page.getByRole("heading", { name: "Fotos" })).toBeVisible();
}

test("filters products that need a main image and opens the individual flow", async ({
  page,
}, testInfo) => {
  await signIn(page);
  await openPhotos(page);

  const results = page.getByRole("list", { name: "Productos" });

  await expect(
    results.getByRole("link", { name: /Frazada Invierno/ }),
  ).toBeVisible();
  await expect(
    results.getByRole("link", { name: /Almohada Luna/ }),
  ).toBeVisible();
  await expect(results.getByRole("link", { name: /Frazada Térmica/ })).toHaveCount(
    0,
  );
  await expect(page.getByText("2 productos")).toBeVisible();
  await expect(page.getByText("Falta la foto").first()).toBeVisible();

  await page.getByLabel("Buscar").fill("almohada");
  await expect(
    results.getByRole("link", { name: /Almohada Luna/ }),
  ).toBeVisible();
  await expect(
    results.getByRole("link", { name: /Frazada Invierno/ }),
  ).toHaveCount(0);

  await page.getByLabel("Buscar").fill("");
  await page.getByLabel("Categoría").selectOption("frazada");
  await expect(
    results.getByRole("link", { name: /Frazada Invierno/ }),
  ).toBeVisible();
  await expect(
    results.getByRole("link", { name: /Almohada Luna/ }),
  ).toHaveCount(0);

  await page.getByLabel("Solo sin imagen principal").uncheck();
  await expect(
    results.getByRole("link", { name: /Frazada Térmica/ }),
  ).toBeVisible();
  await expect(
    results.getByRole("link", { name: /Frazada Otoño/ }),
  ).toBeVisible();
  await expect(
    page.getByAltText("Frazada térmica azul con estrellas"),
  ).toBeVisible();

  await attachScreenshot(page, testInfo, "photos-product-list.png");

  await results.getByRole("link", { name: /Frazada Térmica/ }).click();
  await expect(page).toHaveURL(/\/anime\/photos\/new\?product=12$/);
});

test("shows a no-permission state when the member cannot manage the catalog", async ({
  page,
}, testInfo) => {
  await signIn(page, LIMITED_EMAIL);
  await page.goto("/anime/photos");

  await expect(
    page.getByRole("heading", { name: "Sin permiso" }),
  ).toBeVisible();
  await expect(
    page.getByText("No tienes permiso para ver esta sección."),
  ).toBeVisible();
  await expect(page.getByRole("list", { name: "Productos" })).toHaveCount(0);
  await expect(page.getByText("No pudimos cargar los productos.")).toHaveCount(
    0,
  );

  await attachScreenshot(page, testInfo, "photos-no-permission.png");
});

test("starts the group flow from the product list", async ({
  page,
}, testInfo) => {
  await signIn(page);
  await openPhotos(page);

  await page.getByRole("link", { name: "Foto grupal" }).click();
  await expect(page).toHaveURL(/\/anime\/photos\/new\?kind=group$/);

  await attachScreenshot(page, testInfo, "photos-group-flow.png");
});

test("edits one photo with pointer corners, uploads it and approves it", async ({
  page,
}, testInfo) => {
  await signIn(page);
  await page.goto("/anime/photos/new?product=13");

  await expect(page.getByTestId("photo-page-heading")).toHaveText(
    "Frazada Invierno",
  );

  const imageBase64 = await page.evaluate(() => {
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
    context.fillText("Frazada", 250, 320);
    return canvas.toDataURL("image/png").split(",")[1] ?? "";
  });

  await page.getByLabel("Tomar foto").setInputFiles({
    name: "frazada-invierno.png",
    mimeType: "image/png",
    buffer: Buffer.from(imageBase64, "base64"),
  });

  await expect(page.getByTestId("photo-editor")).toBeVisible();
  await expect(
    page.getByRole("group", { name: "Corrección de luz" }),
  ).toBeVisible();

  const canvas = page.getByTestId("corner-canvas");
  const box = await canvas.boundingBox();
  if (!box) {
    throw new Error("The corner canvas has no bounding box");
  }

  const start = {
    x: box.x + box.width * 0.1,
    y: box.y + box.height * 0.1,
  };
  const target = {
    x: box.x + box.width * 0.3,
    y: box.y + box.height * 0.35,
  };

  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await expect(page.getByTestId("corner-loupe")).toBeVisible();
  await attachScreenshot(page, testInfo, "photo-corner-loupe.png");
  await page.mouse.move(target.x, target.y, { steps: 8 });
  await page.mouse.up();

  const uploadResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.status() === 201 &&
      response.url().includes("/api/backend/api/v1/staff/photos"),
  );

  await page.getByRole("button", { name: "Enviar foto" }).click();
  const created = (await (await uploadResponse).json()) as {
    corners: Array<{ x: number; y: number }>;
  };
  expect(created.corners[0]?.x).toBeCloseTo(0.3, 1);
  expect(created.corners[0]?.y).toBeCloseTo(0.35, 1);

  await expect(page.getByTestId("photo-state-label")).toHaveText("En espera", {
    timeout: 15_000,
  });
  await attachScreenshot(page, testInfo, "photo-ready-pending.png");

  await page.getByRole("button", { name: "Aprobar" }).click();
  await expect(page.getByTestId("photo-state-label")).toHaveText(
    "En el carrusel",
  );
  await expect(page).toHaveURL(/\/anime\/photos\/new\?product=13$/);

  const card = page.getByTestId("photo-submission-card");
  await expect(card).toHaveAttribute("data-state", "approved");
  await expect(card).toHaveClass(/border-accent/);
  await attachScreenshot(page, testInfo, "photo-approved.png");

  await page.getByRole("button", { name: "Quitar del carrusel" }).click();
  await expect(page.getByTestId("photo-state-label")).toHaveText("En espera");
  await expect(page).toHaveURL(/\/anime\/photos\/new\?product=13$/);
  await expect(card).toHaveAttribute("data-state", "pending");
  await expect(card).not.toHaveClass(/border-accent/);
});
