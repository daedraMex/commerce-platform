import type { ProductImage, StaffProduct } from "@commerce-platform/api-client";

export type PhotoProduct = Omit<StaffProduct, "main_image"> & {
  main_image: ProductImage | null;
};

export function toPhotoProduct(product: StaffProduct): PhotoProduct {
  return {
    ...product,
    main_image: (product.main_image ?? null) as ProductImage | null,
  };
}
