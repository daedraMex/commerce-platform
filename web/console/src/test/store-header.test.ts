import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { axiosInstance } from "@commerce-platform/api-client";

import { installStoreHeader } from "@/lib/api/store-header";

const originalAdapter = axiosInstance.defaults.adapter;

function captureRequest() {
  let headerValue: string | null = null;
  let headerPresent = false;

  axiosInstance.defaults.adapter = async (config) => {
    headerValue = config.headers.get("X-Store") as string | null;
    headerPresent = config.headers.has("X-Store");
    return {
      data: null,
      status: 200,
      statusText: "OK",
      headers: {},
      config,
    };
  };

  return () => ({ headerValue, headerPresent });
}

beforeEach(() => {
  installStoreHeader();
});

afterEach(() => {
  axiosInstance.defaults.adapter = originalAdapter;
  window.history.replaceState({}, "", "/");
});

describe("store header interceptor", () => {
  it("turns the store segment into the X-Store header", async () => {
    window.history.replaceState({}, "", "/anime/photos");
    const seen = captureRequest();

    await axiosInstance.get("/api/v1/staff/products/");

    expect(seen().headerValue).toBe("anime");
  });

  it("follows the URL when the store segment changes", async () => {
    window.history.replaceState({}, "", "/home/orders");
    const seen = captureRequest();

    await axiosInstance.get("/api/v1/staff/products/");

    expect(seen().headerValue).toBe("home");
  });

  it("does not send a store header outside a store route", async () => {
    window.history.replaceState({}, "", "/sign-in");
    const seen = captureRequest();

    await axiosInstance.get("/api/v1/me/");

    expect(seen().headerPresent).toBe(false);
  });

  it("keeps an explicit X-Store header", async () => {
    window.history.replaceState({}, "", "/anime");
    const seen = captureRequest();

    await axiosInstance.get("/api/v1/staff/products/", {
      headers: { "X-Store": "kawaii" },
    });

    expect(seen().headerValue).toBe("kawaii");
  });
});
