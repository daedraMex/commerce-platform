import { expect, test } from "@playwright/test";

const email = process.env.E2E_STAFF_EMAIL ?? "e2e@example.com";
const password = process.env.E2E_STAFF_PASSWORD;

test.skip(!password, "E2E_STAFF_PASSWORD is required for the level-2 stack.");

test("staff signs in to the home store", async ({ page }, testInfo) => {
  await page.goto("/home");

  await expect(page).toHaveURL(/\/sign-in\?next=%2Fhome$/);
  await page.getByLabel("Correo electrónico").fill(email);
  await page.getByLabel("Contraseña").fill(password ?? "");
  await page.getByRole("button", { name: "Entrar" }).click();

  await expect(page).toHaveURL(/\/home$/);
  await expect(page.getByRole("heading", { name: "Quetzal" })).toBeVisible();
  await expect(page.getByText("Home")).toBeVisible();

  await testInfo.attach("signed-in-level-2.png", {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png",
  });
});
