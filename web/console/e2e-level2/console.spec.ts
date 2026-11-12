import { expect, test } from "@playwright/test";

test("the console serves the home store", async ({ page }) => {
  await page.goto("/home");

  await expect(page.getByRole("heading", { name: "Quetzal" })).toBeVisible();
});
