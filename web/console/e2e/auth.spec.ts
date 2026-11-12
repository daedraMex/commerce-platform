import { expect, test } from "@playwright/test";

import {
  REFRESH_EMAIL,
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

test("an unauthenticated visitor is sent to sign in", async ({
  page,
}, testInfo) => {
  await page.goto("/anime");

  await expect(page).toHaveURL(/\/sign-in\?next=%2Fanime$/);
  await expect(
    page.getByRole("heading", { name: "Iniciar sesión" }),
  ).toBeVisible();
  await attachScreenshot(page, testInfo, "unauthenticated-sign-in.png");
});

test("signs in, keeps the session and signs out", async ({ page }, testInfo) => {
  await page.goto("/sign-in?next=%2Fanime");
  await page.getByLabel("Correo electrónico").fill(VALID_EMAIL);
  await page.getByLabel("Contraseña").fill(VALID_PASSWORD);
  await page.getByRole("button", { name: "Entrar" }).click();

  await expect(page).toHaveURL(/\/anime$/);
  await expect(page.getByRole("heading", { name: "Quetzal" })).toBeVisible();
  await expect(page.getByText("Anime")).toBeVisible();

  const cookies = await page.context().cookies();
  const access = cookies.find((cookie) => cookie.name === "quetzal_access");
  const refresh = cookies.find((cookie) => cookie.name === "quetzal_refresh");

  expect(access).toMatchObject({ httpOnly: true, secure: true, sameSite: "Lax" });
  expect(refresh).toMatchObject({
    httpOnly: true,
    secure: true,
    sameSite: "Lax",
  });
  expect(await page.evaluate(() => document.cookie)).not.toContain("quetzal_");

  await attachScreenshot(page, testInfo, "signed-in.png");

  await page.getByRole("button", { name: "Salir" }).click();
  await expect(page).toHaveURL(/\/sign-in$/);

  const cleared = await page.context().cookies();
  expect(cleared.some((cookie) => cookie.name === "quetzal_access")).toBeFalsy();
  expect(cleared.some((cookie) => cookie.name === "quetzal_refresh")).toBeFalsy();

  await page.goto("/anime");
  await expect(page).toHaveURL(/\/sign-in\?next=%2Fanime$/);
  await attachScreenshot(page, testInfo, "signed-out.png");
});

test("refreshes an expired access token without asking again", async ({
  page,
}, testInfo) => {
  await page.goto("/sign-in");
  await page.getByLabel("Correo electrónico").fill(REFRESH_EMAIL);
  await page.getByLabel("Contraseña").fill(VALID_PASSWORD);
  await page.getByRole("button", { name: "Entrar" }).click();

  await expect(page).toHaveURL(/\/anime$/);
  await expect(page.getByRole("heading", { name: "Quetzal" })).toBeVisible();

  const cookies = await page.context().cookies();
  expect(
    cookies.find((cookie) => cookie.name === "quetzal_access")?.value,
  ).toBe("access-2");
  expect(
    cookies.find((cookie) => cookie.name === "quetzal_refresh")?.value,
  ).toBe("refresh-2");

  await attachScreenshot(page, testInfo, "refreshed-session.png");
});
