import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";

import { resetRefreshCache } from "@/lib/auth/refresh";
import { server } from "@/mocks/server";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => {
  server.resetHandlers();
  resetRefreshCache();
});
afterAll(() => server.close());
