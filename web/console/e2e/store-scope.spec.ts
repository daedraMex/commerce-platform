import { expect, test } from "@playwright/test";

import { VALID_EMAIL, VALID_PASSWORD } from "../src/mocks/handlers";

async function signIn(page: import("@playwright/test").Page) {
  await page.goto("/sign-in?next=%2Fanime");
  await page.getByLabel("Correo electrónico").fill(VALID_EMAIL);
  await page.getByLabel("Contraseña").fill(VALID_PASSWORD);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page).toHaveURL(/\/anime$/);
}

async function openPhotos(page: import("@playwright/test").Page) {
  await page.getByRole("link", { name: "Fotos" }).click();
  await expect(page).toHaveURL(/\/anime\/photos$/);
  await expect(page.getByRole("heading", { name: "Fotos" })).toBeVisible();
}

test("keeps each store's cached products apart and sends the new X-Store", async ({
  page,
}, testInfo) => {
  await signIn(page);
  await openPhotos(page);

  const results = page.getByRole("list", { name: "Productos" });
  await expect(
    results.getByRole("link", { name: /Frazada Invierno/ }),
  ).toBeVisible();

  const requests: Array<string | undefined> = [];
  let meRequests = 0;
  page.on("request", (request) => {
    const url = request.url();
    if (url.includes("/api/backend/api/v1/staff/products/")) {
      requests.push(request.headers()["x-store"]);
    }
    if (url.includes("/api/backend/api/v1/me/")) {
      meRequests += 1;
    }
  });

  const homeProducts = page.waitForRequest(
    (request) =>
      request.method() === "GET" &&
      request.url().includes("/api/backend/api/v1/staff/products/") &&
      request.headers()["x-store"] === "home",
  );

  await page.getByLabel("Tienda").selectOption("home");
  const request = await homeProducts;
  expect(request.headers()["x-store"]).toBe("home");

  await expect(page).toHaveURL(/\/home\/photos$/);
  await expect(
    results.getByRole("link", { name: /Manta Hogar/ }),
  ).toBeVisible();
  await expect(
    results.getByRole("link", { name: /Frazada Invierno/ }),
  ).toHaveCount(0);
  await expect(
    results.getByRole("link", { name: /Almohada Luna/ }),
  ).toHaveCount(0);
  expect(requests).toContain("home");
  expect(meRequests).toBe(0);

  await testInfo.attach("store-scoped-products.png", {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png",
  });
});

test("switches store from a detail route to the same section's list", async ({
  page,
}, testInfo) => {
  await signIn(page);
  await page.goto("/anime/photos/new?product=13");
  await expect(page).toHaveURL(/\/anime\/photos\/new\?product=13$/);

  await page.getByLabel("Tienda").selectOption("home");

  await expect(page).toHaveURL(/\/home\/photos$/);
  await expect(page.getByRole("heading", { name: "Fotos" })).toBeVisible();
  await expect(
    page.getByRole("list", { name: "Productos" }).getByRole("link", {
      name: /Manta Hogar/,
    }),
  ).toBeVisible();

  await testInfo.attach("store-switch-from-detail.png", {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png",
  });
});
