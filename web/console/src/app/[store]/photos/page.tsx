import { PermissionGate } from "@/features/auth/organisms/permission-gate";
import { PhotosProductList } from "@/features/photos/organisms/photos-product-list";

export default async function PhotosPage({
  params,
}: {
  params: Promise<{ store: string }>;
}) {
  const { store } = await params;

  return (
    <PermissionGate store={store} permission="catalog.manage">
      <PhotosProductList store={store} />
    </PermissionGate>
  );
}
