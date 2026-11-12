---
status: accepted
---

# The Phase 14 mobile app uses Kotlin Multiplatform with Compose Multiplatform and Material 3

The Phase 14 customer app is built with Kotlin Multiplatform and Compose Multiplatform, styled with Material 3, so Android and iOS ship from one codebase with shared Kotlin logic and shared UI. Each store's theme is a Material 3 color scheme generated from a seed color, and the seed is the store's existing `accent_color` (ADR-0026), so the app follows the same per-store branding as Quetzal without a new field.

The app consumes the same OpenAPI schema as the web clients, `packages/api-client/openapi.json`. A Kotlin client is generated from it in Phase 14; the TypeScript `packages/api-client` is not used by the app.

Design follows the Material 3 guidelines (m3.material.io). `github.com/charliesbot/android-design` is a reference only: on 2026-11-12 it declared no license, which means all rights reserved, so nothing is copied from it unless a license that allows commercial use is confirmed first.

## Considered Options

- React Native with Expo: rejected. It adds one more JavaScript runtime and toolchain (Metro, EAS Build, EAS Update) to maintain next to Next.js, while Kotlin Multiplatform gives native Material 3 components and business logic shared between Android and iOS in Kotlin.

## Consequences

- Phase 14 needs a Kotlin OpenAPI generator, chosen at its `/to-spec`, that runs from `packages/api-client/openapi.json` like `pnpm generate:client` does for TypeScript.
- CI gains a Gradle build for `mobile/`.
- The night factory needs a mobile area before it can take mobile tickets.
- Store releases no longer use EAS Build and EAS Update; the release path for Google Play and the App Store is decided in Phase 14.
