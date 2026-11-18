import { HttpResponse, http } from "msw";

import type {
  Category,
  Me,
  ProductImage,
  StaffProduct,
  TokenPairResponse,
} from "@commerce-platform/api-client";

export const VALID_EMAIL = "ana@example.com";
export const VALID_PASSWORD = "correct-horse";
export const REFRESH_EMAIL = "refresh@example.com";
export const NO_MEMBERSHIP_EMAIL = "nomembership@example.com";
export const LIMITED_EMAIL = "limited@example.com";

const MEMBERSHIPS: Me["memberships"] = [
  {
    store: { slug: "anime", name: "Anime", accent_color: "#4f46e5" },
    role: "store_admin",
    permissions: ["catalog.manage", "inventory.adjust"],
  },
  {
    store: { slug: "home", name: "Home", accent_color: "#0ea5e9" },
    role: "store_admin",
    permissions: ["catalog.manage", "inventory.adjust"],
  },
];

const MAIN_IMAGE: ProductImage = {
  alt_text: "Frazada térmica azul con estrellas",
  url: "https://media.example.test/stores/1/media/frazada-termica.jpg",
  thumbnail_url:
    "https://media.example.test/stores/1/media/renditions/frazada-termica-320w-v1.webp",
  medium_url:
    "https://media.example.test/stores/1/media/renditions/frazada-termica-800w-v1.webp",
  width: 1200,
  height: 800,
  role: "main",
  position: 1,
  variant: null,
};

const AUTUMN_IMAGE: ProductImage = {
  ...MAIN_IMAGE,
  alt_text: "Frazada de otoño en tonos tierra",
  url: "https://media.example.test/stores/1/media/frazada-otono.jpg",
  thumbnail_url:
    "https://media.example.test/stores/1/media/renditions/frazada-otono-320w-v1.webp",
  medium_url:
    "https://media.example.test/stores/1/media/renditions/frazada-otono-800w-v1.webp",
};

export type MockPhotoProduct = Omit<StaffProduct, "main_image"> & {
  main_image: ProductImage | null;
};

export const PHOTO_CATEGORIES: Category[] = [
  {
    name: "Almohada",
    slug: "almohada",
    sku_code: "ALM",
    shape: "contour",
    options: [],
  },
  {
    name: "Frazada",
    slug: "frazada",
    sku_code: "FRZ",
    shape: "rectangle",
    options: [],
  },
];

export const PHOTO_PRODUCTS: MockPhotoProduct[] = [
  {
    id: 12,
    name: "Frazada Térmica",
    slug: "frazada-termica",
    category: { name: "Frazada", slug: "frazada" },
    needs_main_image: false,
    main_image: MAIN_IMAGE,
  },
  {
    id: 13,
    name: "Frazada Invierno",
    slug: "frazada-invierno",
    category: { name: "Frazada", slug: "frazada" },
    needs_main_image: true,
    main_image: null,
  },
  {
    id: 14,
    name: "Almohada Luna",
    slug: "almohada-luna",
    category: { name: "Almohada", slug: "almohada" },
    needs_main_image: true,
    main_image: null,
  },
  {
    id: 15,
    name: "Frazada Otoño",
    slug: "frazada-otono",
    category: { name: "Frazada", slug: "frazada" },
    needs_main_image: false,
    main_image: AUTUMN_IMAGE,
  },
];

function normalize(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function photoProductsPage(request: Request) {
  const url = new URL(request.url);
  const search = url.searchParams.get("search")?.trim() ?? "";
  const category = url.searchParams.get("category") ?? "";
  const needsMainImage = url.searchParams.get("needs_main_image");
  const page = Math.max(1, Number(url.searchParams.get("page") ?? "1") || 1);
  const pageSize = Math.max(
    1,
    Math.min(100, Number(url.searchParams.get("page_size") ?? "20") || 20),
  );

  let items = PHOTO_PRODUCTS;
  if (search) {
    items = items.filter((product) =>
      normalize(product.name).includes(normalize(search)),
    );
  }
  if (category) {
    items = items.filter((product) => product.category.slug === category);
  }
  if (needsMainImage === "true") {
    items = items.filter((product) => product.needs_main_image);
  } else if (needsMainImage === "false") {
    items = items.filter((product) => !product.needs_main_image);
  }

  const start = (page - 1) * pageSize;
  const results = items.slice(start, start + pageSize);
  const hasNext = start + pageSize < items.length;
  const hasPrevious = page > 1 && start < items.length;

  return {
    count: items.length,
    next: hasNext ? `http://backend.test/api/v1/staff/products/?page=${page + 1}` : null,
    previous: hasPrevious
      ? `http://backend.test/api/v1/staff/products/?page=${page - 1}`
      : null,
    results,
  };
}

function membershipsFor(email: string): Me["memberships"] {
  if (email !== LIMITED_EMAIL) {
    return MEMBERSHIPS;
  }

  return MEMBERSHIPS.map((membership) => ({
    ...membership,
    role: "store_admin",
    permissions: ["inventory.adjust"],
  }));
}

type MockState = {
  email: string;
  accessToken: string;
  refreshToken: string;
  accessValid: boolean;
  accessVersion: number;
  refreshVersion: number;
  expireAfterValidation: boolean;
  memberships: Me["memberships"];
  refreshCalls: number;
};

function initialState(): MockState {
  return {
    email: VALID_EMAIL,
    accessToken: "access-1",
    refreshToken: "refresh-1",
    accessValid: false,
    accessVersion: 1,
    refreshVersion: 1,
    expireAfterValidation: false,
    memberships: MEMBERSHIPS,
    refreshCalls: 0,
  };
}

let state = initialState();

export function resetMockState(): void {
  state = initialState();
}

export function currentMockState(): Readonly<MockState> {
  return state;
}

function problem(status: number, code: string, detail: string) {
  return HttpResponse.json(
    {
      type: "about:blank",
      title: status === 401 ? "Unauthorized" : "Bad Request",
      status,
      detail,
      code,
    },
    {
      status,
      headers: { "content-type": "application/problem+json" },
    },
  );
}

function tokenPair(): TokenPairResponse {
  return {
    access: `access-${state.accessVersion}`,
    refresh: `refresh-${state.refreshVersion}`,
  };
}

function meBody(): Me {
  return {
    user: { id: 1, email: state.email },
    memberships: state.memberships,
  };
}

function authorized(request: Request): boolean {
  return (
    state.accessValid &&
    request.headers.get("authorization") === `Bearer ${state.accessToken}`
  );
}

export const handlers = [
  http.post("*/api/v1/auth/token/", async ({ request }) => {
    const body = (await request.json()) as {
      email?: string;
      password?: string;
    };
    const email = body.email ?? "";
    const knownEmail =
      email === VALID_EMAIL ||
      email === REFRESH_EMAIL ||
      email === NO_MEMBERSHIP_EMAIL ||
      email === LIMITED_EMAIL;

    if (!knownEmail || body.password !== VALID_PASSWORD) {
      return problem(401, "invalid_credentials", "Invalid email or password.");
    }

    state = {
      ...initialState(),
      email,
      accessValid: true,
      expireAfterValidation: email === REFRESH_EMAIL,
      memberships:
        email === NO_MEMBERSHIP_EMAIL ? [] : membershipsFor(email),
    };

    return HttpResponse.json(tokenPair());
  }),

  http.post("*/api/v1/auth/token/refresh/", async ({ request }) => {
    const body = (await request.json()) as { refresh?: string };
    state.refreshCalls += 1;

    if (body.refresh !== state.refreshToken) {
      return problem(401, "token_invalid", "Token is invalid");
    }

    state.accessVersion += 1;
    state.refreshVersion += 1;
    state.accessToken = `access-${state.accessVersion}`;
    state.refreshToken = `refresh-${state.refreshVersion}`;
    state.accessValid = true;

    return HttpResponse.json(tokenPair());
  }),

  http.post("*/api/v1/auth/logout/", async ({ request }) => {
    const body = (await request.json()) as { refresh?: string };

    if (body.refresh !== state.refreshToken) {
      return problem(401, "token_invalid", "Token is invalid");
    }

    state.accessValid = false;
    state.refreshToken = "";

    return new HttpResponse(null, { status: 204 });
  }),

  http.get("*/api/v1/me/", ({ request }) => {
    if (!authorized(request)) {
      return problem(
        401,
        "token_invalid",
        "Given token not valid for any token type",
      );
    }

    const body = meBody();

    if (state.expireAfterValidation) {
      state.expireAfterValidation = false;
      state.accessValid = false;
    }

    return HttpResponse.json(body);
  }),

  http.get("*/api/v1/catalog/categories/", () => {
    return HttpResponse.json(PHOTO_CATEGORIES);
  }),

  http.get("*/api/v1/staff/products/", ({ request }) => {
    if (!authorized(request)) {
      return problem(
        401,
        "not_authenticated",
        "Authentication credentials were not provided.",
      );
    }

    return HttpResponse.json(photoProductsPage(request));
  }),
];
