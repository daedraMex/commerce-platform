import { HttpResponse, http } from "msw";

import type {
  CarouselImage,
  Category,
  Me,
  PhotoSubmission,
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

const HOME_PHOTO_PRODUCTS: MockPhotoProduct[] = [
  {
    id: 21,
    name: "Manta Hogar",
    slug: "manta-hogar",
    category: { name: "Frazada", slug: "frazada" },
    needs_main_image: true,
    main_image: null,
  },
  {
    id: 22,
    name: "Cojín Nube",
    slug: "cojin-nube",
    category: { name: "Almohada", slug: "almohada" },
    needs_main_image: true,
    main_image: null,
  },
];

const PHOTO_PRODUCTS_BY_STORE: Record<string, MockPhotoProduct[]> = {
  anime: PHOTO_PRODUCTS,
  home: HOME_PHOTO_PRODUCTS,
};

function normalize(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function photoProductsPage(
  request: Request,
  storeProducts: MockPhotoProduct[],
) {
  const url = new URL(request.url);
  const search = url.searchParams.get("search")?.trim() ?? "";
  const category = url.searchParams.get("category") ?? "";
  const needsMainImage = url.searchParams.get("needs_main_image");
  const page = Math.max(1, Number(url.searchParams.get("page") ?? "1") || 1);
  const pageSize = Math.max(
    1,
    Math.min(100, Number(url.searchParams.get("page_size") ?? "20") || 20),
  );

  let items = storeProducts;
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

type PhotoScenario = "ready" | "failed" | "conflict";

type MockPreview = {
  bytes: Uint8Array;
  contentType: string;
};

type PhotoMockState = {
  submissions: Map<number, PhotoSubmission>;
  polls: Map<number, number>;
  previews: Map<number, MockPreview>;
  carousels: Map<number, CarouselImage[]>;
  nextId: number;
};

const REMOVED_IMAGE: CarouselImage = {
  id: 103,
  media_id: 203,
  photo_submission_id: 1003,
  active: false,
  role: "gallery",
  position: 3,
  alt_text: "Frazada retirada del carrusel",
  url: "https://media.example.test/stores/1/media/frazada-retirada.jpg",
  thumbnail_url:
    "https://media.example.test/stores/1/media/renditions/frazada-retirada-320w-v1.webp",
  medium_url:
    "https://media.example.test/stores/1/media/renditions/frazada-retirada-800w-v1.webp",
  width: 1200,
  height: 800,
};

const PENDING_IMAGE: CarouselImage = {
  id: null,
  media_id: 204,
  photo_submission_id: 1004,
  active: false,
  role: null,
  position: null,
  alt_text: "Frazada esperando aprobación",
  url: "https://media.example.test/stores/1/media/frazada-espera.jpg",
  thumbnail_url:
    "https://media.example.test/stores/1/media/renditions/frazada-espera-320w-v1.webp",
  medium_url:
    "https://media.example.test/stores/1/media/renditions/frazada-espera-800w-v1.webp",
  width: 1200,
  height: 800,
};

function initialCarousels(): Map<number, CarouselImage[]> {
  return new Map([
    [
      12,
      [
        {
          ...MAIN_IMAGE,
          id: 101,
          media_id: 201,
          photo_submission_id: 1001,
          active: true,
          role: "main",
          position: 1,
        },
        {
          ...AUTUMN_IMAGE,
          id: 102,
          media_id: 202,
          photo_submission_id: 1002,
          active: true,
          role: "gallery",
          position: 2,
        },
        REMOVED_IMAGE,
        PENDING_IMAGE,
      ],
    ],
  ]);
}

function initialPhotoState(): PhotoMockState {
  return {
    submissions: new Map(),
    polls: new Map(),
    previews: new Map(),
    carousels: initialCarousels(),
    nextId: 100,
  };
}

let photoState = initialPhotoState();

export function resetPhotoMockState(): void {
  photoState = initialPhotoState();
}

const PREVIEW_PNG = Uint8Array.from(
  atob(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2n3sAAAAASUVORK5CYII=",
  ),
  (character) => character.charCodeAt(0),
);

function photoScenario(targetProduct: number | null): PhotoScenario {
  if (targetProduct === 14) {
    return "failed";
  }
  if (targetProduct === 15) {
    return "conflict";
  }
  return "ready";
}

function photoProblem(status: number, code: string, detail: string) {
  return problem(status, code, detail);
}

function storedSubmission(id: number): PhotoSubmission | undefined {
  return photoState.submissions.get(id);
}

function saveSubmission(submission: PhotoSubmission): PhotoSubmission {
  photoState.submissions.set(submission.id, submission);
  return submission;
}

function readyResult(id: number) {
  return {
    media_id: id + 1000,
    url: `https://media.example.test/stores/1/media/photo-${id}.jpg`,
    thumbnail_url: `https://media.example.test/stores/1/media/renditions/photo-${id}-320w-v1.webp`,
    medium_url: `https://media.example.test/stores/1/media/renditions/photo-${id}-800w-v1.webp`,
    width: 1200,
    height: 1500,
  };
}

function advanceSubmission(
  submission: PhotoSubmission,
  scenario: PhotoScenario,
): PhotoSubmission {
  if (submission.status !== "uploaded" && submission.status !== "processing") {
    return submission;
  }

  const polls = photoState.polls.get(submission.id) ?? 0;
  photoState.polls.set(submission.id, polls + 1);

  if (polls === 0) {
    return saveSubmission({
      ...submission,
      status: "processing",
      attempts: Math.max(1, submission.attempts),
      updated_at: new Date().toISOString(),
      version: submission.version + 1,
    });
  }

  if (scenario === "failed") {
    return saveSubmission({
      ...submission,
      status: "failed",
      failure_code: "quad_self_intersecting",
      failure_message: "The corners cross each other; drag them into order.",
      result: null,
      updated_at: new Date().toISOString(),
      version: submission.version + 1,
    });
  }

  return saveSubmission({
    ...submission,
    status: "ready",
    result: readyResult(submission.id),
    updated_at: new Date().toISOString(),
    version: submission.version + 1,
  });
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
  resetPhotoMockState();
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

function normalizeProductIds(value: unknown): number[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  const ids = new Set<number>();
  for (const item of value) {
    if (typeof item !== "number" || !Number.isInteger(item) || item < 1) {
      return null;
    }
    ids.add(item);
  }
  return [...ids].sort((a, b) => a - b);
}

export const handlers = [
  http.get("*/api/v1/staff/products/:id/images/", ({ request, params }) => {
    if (!authorized(request)) {
      return problem(
        401,
        "not_authenticated",
        "Authentication credentials were not provided.",
      );
    }

    const productId = Number(params.id);
    const images = photoState.carousels.get(productId) ?? [];
    return HttpResponse.json({ product_id: productId, images });
  }),

  http.put(
    "*/api/v1/staff/products/:id/images/order/",
    async ({ request, params }) => {
      if (!authorized(request)) {
        return problem(
          401,
          "not_authenticated",
          "Authentication credentials were not provided.",
        );
      }

      const productId = Number(params.id);
      let body: { image_ids?: unknown } = {};
      try {
        body = (await request.json()) as { image_ids?: unknown };
      } catch {
        return problem(400, "validation_error", "The body must be JSON.");
      }
      const imageIds = body.image_ids;
      if (!Array.isArray(imageIds) || imageIds.some((id) => typeof id !== "number")) {
        return problem(
          400,
          "catalog_invalid_image_order",
          "The order must list the active image ids.",
        );
      }

      const current = photoState.carousels.get(productId) ?? [];
      const active = current.filter((image) => image.active);
      const inactive = current.filter((image) => !image.active);
      const byId = new Map(active.map((image) => [image.id, image]));
      if (
        imageIds.length !== active.length ||
        new Set(imageIds).size !== imageIds.length ||
        imageIds.some((id) => !byId.has(id))
      ) {
        return problem(
          400,
          "catalog_invalid_image_order",
          "The order must list exactly this product's active image ids, once each.",
        );
      }

      const reordered = imageIds.map((id, index) => ({
        ...(byId.get(id) as CarouselImage),
        position: index + 1,
        role: index === 0 ? "main" : "gallery",
      }));
      const images = [...reordered, ...inactive];
      photoState.carousels.set(productId, images);
      return HttpResponse.json({ product_id: productId, images });
    },
  ),

  http.post("*/api/v1/staff/photos/", async ({ request }) => {
    if (!authorized(request)) {
      return problem(
        401,
        "not_authenticated",
        "Authentication credentials were not provided.",
      );
    }

    let form: FormData;
    try {
      form = await request.formData();
    } catch {
      return problem(400, "validation_error", "The multipart body is malformed.");
    }

    const targetValue = form.get("target_product");
    const targetProduct =
      typeof targetValue === "string" && targetValue.length > 0
        ? Number(targetValue)
        : null;
    const scenario = photoScenario(targetProduct);

    if (scenario === "conflict") {
      return problem(
        409,
        "idempotency_conflict",
        "This idempotency key was already used with a different request.",
      );
    }

    const parseJson = (value: FormDataEntryValue | null): unknown => {
      if (typeof value !== "string" || value.length === 0) {
        return null;
      }
      try {
        return JSON.parse(value) as unknown;
      } catch {
        return null;
      }
    };

    const now = new Date().toISOString();
    const id = photoState.nextId;
    photoState.nextId += 1;

    const uploadedFile = form.get("file");
    if (
      uploadedFile &&
      typeof uploadedFile === "object" &&
      "arrayBuffer" in uploadedFile
    ) {
      const file = uploadedFile as File;
      photoState.previews.set(id, {
        bytes: new Uint8Array(await file.arrayBuffer()),
        contentType: file.type || "image/jpeg",
      });
    }

    const submission: PhotoSubmission = {
      id,
      kind: String(form.get("kind") ?? "rectangle"),
      status: "uploaded",
      failure_code: "",
      failure_message: "",
      preview_url: `/api/v1/staff/photos/${id}/preview/`,
      result: null,
      linked_product_ids: [],
      pipeline_version: "2026-11-11.2",
      attempts: 0,
      redos: 0,
      redos_remaining: 5,
      version: 1,
      applied_at: null,
      discarded_at: null,
      target_product_id: targetProduct,
      photographed_variant_id: null,
      light_correction: form.get("light_correction") !== "false",
      corners: parseJson(form.get("corners")),
      crop: parseJson(form.get("crop")),
      created_at: now,
      updated_at: now,
    };

    saveSubmission(submission);
    photoState.polls.set(id, 0);
    return HttpResponse.json(submission, { status: 201 });
  }),

  http.get("*/api/v1/staff/photos/:id/preview/", ({ request, params }) => {
    if (!authorized(request)) {
      return problem(
        401,
        "not_authenticated",
        "Authentication credentials were not provided.",
      );
    }

    const submission = storedSubmission(Number(params.id));
    if (!submission || submission.discarded_at) {
      return problem(
        404,
        "not_found",
        "No photo submission matches this id in this store.",
      );
    }

    const preview = photoState.previews.get(submission.id);
    return new HttpResponse(preview?.bytes ?? PREVIEW_PNG, {
      headers: { "content-type": preview?.contentType ?? "image/png" },
    });
  }),

  http.post("*/api/v1/staff/photos/:id/apply/", async ({ request, params }) => {
    if (!authorized(request)) {
      return problem(
        401,
        "not_authenticated",
        "Authentication credentials were not provided.",
      );
    }

    const submission = storedSubmission(Number(params.id));
    if (!submission) {
      return problem(
        404,
        "not_found",
        "No photo submission matches this id in this store.",
      );
    }

    if (submission.kind === "group") {
      let body: { product_ids?: unknown } = {};
      try {
        body = (await request.json()) as { product_ids?: unknown };
      } catch {
        body = {};
      }
      const productIds = normalizeProductIds(body.product_ids);
      if (
        !productIds ||
        productIds.length === 0 ||
        submission.status !== "ready" ||
        submission.discarded_at
      ) {
        return photoProblem(
          409,
          "submission_cannot_apply",
          "Only a ready group photo with products can be applied.",
        );
      }

      return HttpResponse.json(
        saveSubmission({
          ...submission,
          applied_at: submission.applied_at ?? new Date().toISOString(),
          linked_product_ids: productIds,
          updated_at: new Date().toISOString(),
          version: submission.version + 1,
        }),
      );
    }

    if (
      submission.status !== "ready" ||
      submission.applied_at ||
      submission.discarded_at
    ) {
      return photoProblem(
        409,
        "submission_cannot_apply",
        "Only a ready photo can be applied.",
      );
    }

    return HttpResponse.json(
      saveSubmission({
        ...submission,
        applied_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        version: submission.version + 1,
      }),
    );
  }),

  http.post("*/api/v1/staff/photos/:id/links/", async ({ request, params }) => {
    if (!authorized(request)) {
      return problem(
        401,
        "not_authenticated",
        "Authentication credentials were not provided.",
      );
    }

    const submission = storedSubmission(Number(params.id));
    if (!submission) {
      return problem(
        404,
        "not_found",
        "No photo submission matches this id in this store.",
      );
    }

    let body: { product_ids?: unknown } = {};
    try {
      body = (await request.json()) as { product_ids?: unknown };
    } catch {
      return problem(
        400,
        "validation_error",
        "The body must be a JSON object with product_ids.",
      );
    }
    const productIds = normalizeProductIds(body.product_ids);
    if (!productIds) {
      return problem(
        400,
        "validation_error",
        "product_ids must be a list of product ids.",
      );
    }
    if (
      submission.kind !== "group" ||
      submission.status !== "ready" ||
      !submission.applied_at ||
      submission.discarded_at
    ) {
      return photoProblem(
        409,
        "submission_cannot_change_links",
        "Only an applied group photo can change its links.",
      );
    }

    return HttpResponse.json(
      saveSubmission({
        ...submission,
        linked_product_ids: productIds,
        updated_at: new Date().toISOString(),
        version: submission.version + 1,
      }),
    );
  }),

  http.post("*/api/v1/staff/photos/:id/remove/", ({ request, params }) => {
    if (!authorized(request)) {
      return problem(
        401,
        "not_authenticated",
        "Authentication credentials were not provided.",
      );
    }

    const submission = storedSubmission(Number(params.id));
    if (!submission) {
      return problem(
        404,
        "not_found",
        "No photo submission matches this id in this store.",
      );
    }
    if (!submission.applied_at) {
      return photoProblem(
        409,
        "submission_cannot_remove",
        "Only an applied photo can be removed from the carousel.",
      );
    }

    return HttpResponse.json(
      saveSubmission({
        ...submission,
        applied_at: null,
        updated_at: new Date().toISOString(),
        version: submission.version + 1,
      }),
    );
  }),

  http.post("*/api/v1/staff/photos/:id/redo/", async ({ request, params }) => {
    if (!authorized(request)) {
      return problem(
        401,
        "not_authenticated",
        "Authentication credentials were not provided.",
      );
    }

    const submission = storedSubmission(Number(params.id));
    if (!submission) {
      return problem(
        404,
        "not_found",
        "No photo submission matches this id in this store.",
      );
    }
    if (
      submission.status !== "ready" ||
      submission.applied_at ||
      submission.discarded_at
    ) {
      return photoProblem(
        409,
        "submission_cannot_redo",
        "Only a ready photo can be redone.",
      );
    }

    let body: { corners?: unknown; crop?: unknown } = {};
    try {
      body = (await request.json()) as { corners?: unknown; crop?: unknown };
    } catch {
      body = {};
    }

    photoState.polls.set(submission.id, 0);
    return HttpResponse.json(
      saveSubmission({
        ...submission,
        status: "processing",
        corners: body.corners ?? submission.corners,
        crop: body.crop ?? submission.crop,
        result: null,
        updated_at: new Date().toISOString(),
        version: submission.version + 1,
      }),
    );
  }),

  http.post("*/api/v1/staff/photos/:id/retry/", ({ request, params }) => {
    if (!authorized(request)) {
      return problem(
        401,
        "not_authenticated",
        "Authentication credentials were not provided.",
      );
    }

    const submission = storedSubmission(Number(params.id));
    if (!submission) {
      return problem(
        404,
        "not_found",
        "No photo submission matches this id in this store.",
      );
    }
    if (
      submission.status !== "failed" ||
      submission.applied_at ||
      submission.discarded_at
    ) {
      return photoProblem(
        409,
        "submission_cannot_start_processing",
        "Only a failed photo can be retried.",
      );
    }
    if (submission.attempts >= 3) {
      return photoProblem(
        409,
        "submission_attempts_exhausted",
        "This submission already used its processing attempts.",
      );
    }

    photoState.polls.set(submission.id, 0);
    return HttpResponse.json(
      saveSubmission({
        ...submission,
        status: "processing",
        attempts: submission.attempts + 1,
        failure_code: "",
        failure_message: "",
        result: null,
        updated_at: new Date().toISOString(),
        version: submission.version + 1,
      }),
    );
  }),

  http.post("*/api/v1/staff/photos/:id/discard/", ({ request, params }) => {
    if (!authorized(request)) {
      return problem(
        401,
        "not_authenticated",
        "Authentication credentials were not provided.",
      );
    }

    const submission = storedSubmission(Number(params.id));
    if (!submission) {
      return problem(
        404,
        "not_found",
        "No photo submission matches this id in this store.",
      );
    }
    if (submission.applied_at || submission.discarded_at) {
      return photoProblem(
        409,
        "submission_cannot_discard",
        "An applied or already discarded photo cannot be discarded.",
      );
    }

    return HttpResponse.json(
      saveSubmission({
        ...submission,
        discarded_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        version: submission.version + 1,
      }),
    );
  }),

  http.get("*/api/v1/staff/photos/:id/", ({ request, params }) => {
    if (!authorized(request)) {
      return problem(
        401,
        "not_authenticated",
        "Authentication credentials were not provided.",
      );
    }

    const submission = storedSubmission(Number(params.id));
    if (!submission) {
      return problem(
        404,
        "not_found",
        "No photo submission matches this id in this store.",
      );
    }

    return HttpResponse.json(
      advanceSubmission(submission, photoScenario(submission.target_product_id)),
    );
  }),

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

  http.get("*/api/v1/staff/products/:id/", ({ request, params }) => {
    if (!authorized(request)) {
      return problem(
        401,
        "not_authenticated",
        "Authentication credentials were not provided.",
      );
    }

    const store = request.headers.get("X-Store");
    const storeProducts = store ? PHOTO_PRODUCTS_BY_STORE[store] : undefined;
    if (!store) {
      return problem(
        400,
        "store_header_missing",
        "The X-Store header is required.",
      );
    }
    if (!storeProducts) {
      return problem(400, "store_not_found", "No store matches this slug.");
    }

    const product = storeProducts.find(
      (item) => item.id === Number(params.id),
    );
    if (!product) {
      return problem(
        404,
        "not_found",
        "No active product matches this id in this store.",
      );
    }

    return HttpResponse.json(product);
  }),

  http.get("*/api/v1/staff/products/", ({ request }) => {
    if (!authorized(request)) {
      return problem(
        401,
        "not_authenticated",
        "Authentication credentials were not provided.",
      );
    }

    const store = request.headers.get("X-Store");
    const storeProducts = store ? PHOTO_PRODUCTS_BY_STORE[store] : undefined;
    if (!store) {
      return problem(
        400,
        "store_header_missing",
        "The X-Store header is required.",
      );
    }
    if (!storeProducts) {
      return problem(400, "store_not_found", "No store matches this slug.");
    }

    return HttpResponse.json(photoProductsPage(request, storeProducts));
  }),
];
