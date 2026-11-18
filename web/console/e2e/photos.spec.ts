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
