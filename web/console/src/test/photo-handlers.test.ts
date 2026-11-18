// @vitest-environment node
import { beforeEach, describe, expect, it } from "vitest";

import type { PhotoSubmission } from "@commerce-platform/api-client";

import {
  resetMockState,
  VALID_EMAIL,
  VALID_PASSWORD,
} from "@/mocks/handlers";

const BACKEND = "http://backend.test";

async function signIn(): Promise<string> {
  const response = await fetch(`${BACKEND}/api/v1/auth/token/`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email: VALID_EMAIL, password: VALID_PASSWORD }),
  });
  const tokens = (await response.json()) as { access: string };
  return tokens.access;
}

function uploadBody(targetProduct: number): FormData {
  const body = new FormData();
  body.append(
    "file",
    new File([new Uint8Array([255, 216, 255, 217])], "photo.jpg", {
      type: "image/jpeg",
    }),
  );
  body.append("kind", "rectangle");
  body.append("target_product", String(targetProduct));
  body.append(
    "corners",
    JSON.stringify([
      { x: 0.1, y: 0.1 },
      { x: 0.9, y: 0.1 },
      { x: 0.9, y: 0.9 },
      { x: 0.1, y: 0.9 },
    ]),
  );
  return body;
}

async function upload(access: string, targetProduct: number) {
  return fetch(`${BACKEND}/api/v1/staff/photos/`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${access}`,
      "X-Store": "anime",
      "Idempotency-Key": `test-${targetProduct}`,
    },
    body: uploadBody(targetProduct),
  });
}

async function detail(access: string, id: number) {
  const response = await fetch(`${BACKEND}/api/v1/staff/photos/${id}/`, {
    headers: { authorization: `Bearer ${access}`, "X-Store": "anime" },
  });
  return {
    status: response.status,
    body: (await response.json()) as PhotoSubmission,
  };
}

beforeEach(() => {
  resetMockState();
});

describe("photo MSW scenarios", () => {
  it("moves an uploaded photo through processing to ready", async () => {
    const access = await signIn();
    const created = await upload(access, 13);
    expect(created.status).toBe(201);
    const start = (await created.json()) as PhotoSubmission;
    expect(start.status).toBe("uploaded");

    const processing = await detail(access, start.id);
    expect(processing.status).toBe(200);
    expect(processing.body.status).toBe("processing");

    const ready = await detail(access, start.id);
    expect(ready.body.status).toBe("ready");
    expect(ready.body.result).not.toBeNull();

    const preview = await fetch(
      `${BACKEND}/api/v1/staff/photos/${start.id}/preview/`,
      { headers: { authorization: `Bearer ${access}`, "X-Store": "anime" } },
    );
    expect(preview.status).toBe(200);
  });

  it("fails deterministically for the failing product", async () => {
    const access = await signIn();
    const created = await upload(access, 14);
    const start = (await created.json()) as PhotoSubmission;

    const processing = await detail(access, start.id);
    expect(processing.body.status).toBe("processing");

    const failed = await detail(access, start.id);
    expect(failed.body.status).toBe("failed");
    expect(failed.body.failure_code).toBe("quad_self_intersecting");
  });

  it("returns a deterministic idempotency conflict", async () => {
    const access = await signIn();
    const response = await upload(access, 15);

    expect(response.status).toBe(409);
    expect(await response.json()).toMatchObject({
      code: "idempotency_conflict",
      status: 409,
    });
  });
});
