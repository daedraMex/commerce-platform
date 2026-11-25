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

test("crops a group photo to 4:5, selects products in order and manages links", async ({
  page,
}, testInfo) => {
  await signIn(page);
  await openPhotos(page);

  await page.getByRole("link", { name: "Foto grupal" }).click();
  await expect(page).toHaveURL(/\/anime\/photos\/new\?kind=group$/);
  await expect(
    page.getByRole("heading", { name: "Foto grupal" }),
  ).toBeVisible();

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
    context.fillText("Grupo", 320, 320);
    return canvas.toDataURL("image/png").split(",")[1] ?? "";
  });

  await page.getByLabel("Tomar foto").setInputFiles({
    name: "grupo.png",
    mimeType: "image/png",
    buffer: Buffer.from(imageBase64, "base64"),
  });

  await expect(page.getByTestId("photo-editor")).toBeVisible();
  await expect(page.getByTestId("group-product-picker")).toBeVisible();

  const frame = page.getByTestId("crop-frame");
  await expect(frame).toHaveAttribute("data-shape", "group");
  await expect(frame).toHaveAttribute("data-crop-width", /\d/);

  const initialCrop = {
    x: Number(await frame.getAttribute("data-crop-x")),
    y: Number(await frame.getAttribute("data-crop-y")),
    width: Number(await frame.getAttribute("data-crop-width")),
    height: Number(await frame.getAttribute("data-crop-height")),
  };
  expect((initialCrop.width * 800) / (initialCrop.height * 600)).toBeCloseTo(
    0.8,
    2,
  );

  const frameBox = await frame.boundingBox();
  if (!frameBox) {
    throw new Error("The group crop frame has no bounding box");
  }
  await page.mouse.move(
    frameBox.x + frameBox.width / 2,
    frameBox.y + frameBox.height / 2,
  );
  await page.mouse.down();
  await page.mouse.move(
    frameBox.x + frameBox.width / 2 + 18,
    frameBox.y + frameBox.height / 2,
    { steps: 6 },
  );
  await page.mouse.up();

  const movedCrop = {
    x: Number(await frame.getAttribute("data-crop-x")),
    y: Number(await frame.getAttribute("data-crop-y")),
    width: Number(await frame.getAttribute("data-crop-width")),
    height: Number(await frame.getAttribute("data-crop-height")),
  };
  expect(movedCrop.x).toBeGreaterThan(initialCrop.x);
  expect(movedCrop.x).toBeGreaterThanOrEqual(0);
  expect(movedCrop.x + movedCrop.width).toBeLessThanOrEqual(1);
  expect(movedCrop.y).toBeGreaterThanOrEqual(0);
  expect(movedCrop.y + movedCrop.height).toBeLessThanOrEqual(1);
  expect((movedCrop.width * 800) / (movedCrop.height * 600)).toBeCloseTo(
    0.8,
    2,
  );
  await attachScreenshot(page, testInfo, "photos-group-crop.png");

  await page.getByLabel("Buscar").fill("frazada");
  await page.getByRole("checkbox", { name: "Elegir Frazada Invierno" }).check();
  await page.getByRole("checkbox", { name: "Elegir Frazada Térmica" }).check();
  await expect(page.getByTestId("group-product-picker")).toHaveAttribute(
    "data-selected-order",
    "13,12",
  );
  await attachScreenshot(page, testInfo, "photos-group-selection.png");

  const uploadResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.status() === 201 &&
      response.url().includes("/api/backend/api/v1/staff/photos") &&
      !response.url().includes("/apply"),
  );
  await page.getByRole("button", { name: "Enviar foto y continuar" }).click();
  const created = (await (await uploadResponse).json()) as {
    kind: string;
    target_product_id: number | null;
    crop: { x: number; y: number; width: number; height: number };
  };
  expect(created.kind).toBe("group");
  expect(created.target_product_id).toBeNull();
  expect(created.crop.width / created.crop.height).toBeCloseTo(0.8, 2);

  await expect(page.getByTestId("group-photo-state-label")).toHaveText(
    "En espera",
    { timeout: 15_000 },
  );
  await attachScreenshot(page, testInfo, "photos-group-ready.png");

  const applyResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.status() === 200 &&
      response.url().includes("/apply"),
  );
  await page
    .getByRole("button", { name: "Aplicar a 2 productos" })
    .click();
  const appliedBody = (await (await applyResponse).request().postDataJSON()) as {
    product_ids: number[];
  };
  expect(appliedBody.product_ids).toEqual([13, 12]);
  await expect(page.getByTestId("group-photo-state-label")).toHaveText(
    "Aplicada",
  );
  await expect(page.getByTestId("group-photo-status")).toHaveAttribute(
    "data-state",
    "applied",
  );
  await attachScreenshot(page, testInfo, "photos-group-applied.png");

  await page.getByRole("checkbox", { name: "Elegir Frazada Invierno" }).uncheck();
  await page.getByRole("checkbox", { name: "Elegir Frazada Invierno" }).check();
  await expect(page.getByTestId("group-product-picker")).toHaveAttribute(
    "data-selected-order",
    "12,13",
  );

  await page.getByLabel("Buscar").fill("");
  await page.getByRole("checkbox", { name: "Elegir Almohada Luna" }).check();
  await page.getByRole("checkbox", { name: "Elegir Frazada Invierno" }).uncheck();
  await expect(page.getByTestId("group-product-picker")).toHaveAttribute(
    "data-selected-order",
    "12,14",
  );

  const linksResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.status() === 200 &&
      response.url().includes("/links"),
  );
  await page.getByRole("button", { name: "Guardar enlaces" }).click();
  const linksBody = (await (await linksResponse).request().postDataJSON()) as {
    product_ids: number[];
  };
  expect(linksBody.product_ids).toEqual([12, 14]);
  await expect(page.getByRole("status")).toHaveText("Enlaces guardados.");

  await page.getByRole("checkbox", { name: "Elegir Frazada Invierno" }).check();
  await expect(page.getByTestId("group-product-picker")).toHaveAttribute(
    "data-selected-order",
    "12,14,13",
  );

  const reactivateResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.status() === 200 &&
      response.url().includes("/links"),
  );
  await page.getByRole("button", { name: "Guardar enlaces" }).click();
  const reactivatedBody = (await (
    await reactivateResponse
  ).request().postDataJSON()) as { product_ids: number[] };
  expect(reactivatedBody.product_ids).toEqual([12, 14, 13]);
  await attachScreenshot(page, testInfo, "photos-group-links.png");
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

test("redoes a failed photo and shows it processing again", async ({
  page,
}, testInfo) => {
  await signIn(page);
  await page.goto("/anime/photos/new?product=14");

  await expect(page.getByTestId("photo-page-heading")).toHaveText(
    "Almohada Luna",
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
    context.fillText("Almohada", 250, 320);
    return canvas.toDataURL("image/png").split(",")[1] ?? "";
  });

  await page.getByLabel("Tomar foto").setInputFiles({
    name: "almohada-luna.png",
    mimeType: "image/png",
    buffer: Buffer.from(imageBase64, "base64"),
  });

  await expect(page.getByTestId("photo-editor")).toBeVisible();
  await page.getByRole("button", { name: "Enviar foto" }).click();

  const card = page.getByTestId("photo-submission-card");
  await expect(card).toHaveAttribute("data-state", "failed", {
    timeout: 15_000,
  });
  await expect(page.getByTestId("redos-remaining")).toHaveText(
    "Puedes rehacerla 5 veces más",
  );

  const redoButton = page.getByRole("button", {
    name: "Rehacer",
    exact: true,
  });
  await expect(redoButton).toBeEnabled();
  await redoButton.click();

  await expect(page.getByTestId("photo-editor")).toBeVisible();
  const redoResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().includes("/redo"),
  );
  await page.getByRole("button", { name: "Rehacer foto" }).click();

  const response = await redoResponse;
  expect(response.status()).toBe(200);
  expect(((await response.json()) as { status: string }).status).toBe(
    "processing",
  );
  await expect(card).toHaveAttribute("data-state", "processing");
  await expect(page.getByTestId("photo-state-label")).toHaveText("Procesando…");
  await attachScreenshot(page, testInfo, "photos-redo-failed-processing.png");
});

test("reorders the product carousel by touch and shows the new cover", async ({
  page,
}, testInfo) => {
  await signIn(page);
  await page.goto("/anime/photos/new?product=12");

  const panel = page.getByTestId("product-carousel-panel");
  await expect(panel).toBeVisible();
  const items = panel.getByTestId("carousel-image");
  await expect(items.first()).toHaveAttribute(
    "data-carousel-image-id",
    "101",
  );
  await expect(panel.getByTestId("cover-badge")).toHaveText("Portada");
  await attachScreenshot(page, testInfo, "photos-carousel-before.png");

  const firstBox = await items.first().boundingBox();
  if (!firstBox) {
    throw new Error("The first carousel image has no bounding box");
  }
  const handle = panel.getByTestId("carousel-drag-handle").nth(1);
  const handleBox = await handle.boundingBox();
  if (!handleBox) {
    throw new Error("The second carousel drag handle has no bounding box");
  }

  const reorderRequest = page.waitForRequest(
    (request) =>
      request.method() === "PUT" &&
      request.url().includes("/api/v1/staff/products/12/images/order/"),
  );
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [
      {
        x: handleBox.x + handleBox.width / 2,
        y: handleBox.y + handleBox.height / 2,
        id: 1,
      },
    ],
  });
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchMove",
    touchPoints: [
      {
        x: firstBox.x + firstBox.width / 2,
        y: firstBox.y + firstBox.height / 2,
        id: 1,
      },
    ],
  });
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchEnd",
    touchPoints: [],
  });
  await cdp.detach();

  const body = (await (await reorderRequest).postDataJSON()) as {
    image_ids: number[];
  };
  expect(body.image_ids).toEqual([102, 101]);
  await expect(items.first()).toHaveAttribute(
    "data-carousel-image-id",
    "102",
  );
  await expect(panel.getByTestId("cover-badge")).toHaveText("Portada");
  await attachScreenshot(page, testInfo, "photos-carousel-after.png");
});
