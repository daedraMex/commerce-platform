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

async function signIn(page: import("@playwright/test").Page, email: string) {
  await page.goto("/sign-in?next=%2Fanime");
  await page.getByLabel("Correo electrónico").fill(email);
  await page.getByLabel("Contraseña").fill(VALID_PASSWORD);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page).toHaveURL(/\/anime$/);
}

test("switches store by changing only the URL segment", async ({
  page,
}, testInfo) => {
  await signIn(page, VALID_EMAIL);

  await page.getByRole("link", { name: "Fotos" }).click();
  await expect(page).toHaveURL(/\/anime\/photos$/);
  await expect(page.getByRole("heading", { name: "Fotos" })).toBeVisible();

  await page.getByLabel("Tienda").selectOption("home");

  await expect(page).toHaveURL(/\/home\/photos$/);
  await expect(page.getByRole("heading", { name: "Fotos" })).toBeVisible();
  await expect(page.getByLabel("Tienda")).toHaveValue("home");

  const accent = await page
    .locator("[data-console-shell]")
    .evaluate((element) =>
      getComputedStyle(element).getPropertyValue("--accent").trim(),
    );
  expect(accent).toBe("#0ea5e9");

  await attachScreenshot(page, testInfo, "switched-store.png");
});

test("menu follows permissions instead of role names", async ({
  page,
}, testInfo) => {
  await signIn(page, LIMITED_EMAIL);

  const menu = page.getByRole("navigation", { name: "Menú" });

  await expect(menu.getByRole("link", { name: "Inicio" })).toBeVisible();
  await expect(menu.getByRole("link", { name: "Inventario" })).toBeVisible();
  await expect(menu.getByRole("link", { name: "Fotos" })).toHaveCount(0);
  await expect(menu.getByRole("link", { name: "Pedidos" })).toHaveCount(0);

  await attachScreenshot(page, testInfo, "permission-menu.png");
});

test("theme supports light, dark and system", async ({ page }, testInfo) => {
  await signIn(page, VALID_EMAIL);

  const theme = page.getByLabel("Tema");

  await theme.selectOption("dark");
  await expect(page.locator("html")).toHaveClass(/dark/);
  await attachScreenshot(page, testInfo, "theme-dark.png");

  await page.reload();
  await expect(page.getByRole("heading", { name: "Quetzal" })).toBeVisible();
  await expect(page.getByLabel("Tema")).toHaveValue("dark");
  await expect(page.locator("html")).toHaveClass(/dark/);

  await page.getByLabel("Tema").selectOption("light");
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  await attachScreenshot(page, testInfo, "theme-light.png");

  await page.emulateMedia({ colorScheme: "dark" });
  await page.getByLabel("Tema").selectOption("system");
  await expect(page.locator("html")).toHaveClass(/dark/);

  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).not.toHaveClass(/dark/);
});
