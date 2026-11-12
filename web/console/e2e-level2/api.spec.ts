import { expect, test } from "@playwright/test";

const apiURL = process.env.E2E_API_URL ?? "http://127.0.0.1:8000";

test("the API health endpoint answers 200", async ({ request }) => {
  const response = await request.get(`${apiURL}/api/v1/health/live/`);

  expect(response.status()).toBe(200);
  expect(await response.json()).toMatchObject({ status: "ok" });
});
