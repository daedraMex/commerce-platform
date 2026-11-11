import { expect, test } from "@playwright/test";

test("the placeholder console renders the Quetzal heading", async ({ page }) => {
  await page.goto("/anime");

  await expect(page.getByRole("heading", { name: "Quetzal" })).toBeVisible();
});
