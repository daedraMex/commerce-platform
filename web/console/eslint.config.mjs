import next from "eslint-config-next/core-web-vitals";
import boundaries from "eslint-plugin-boundaries";

// Next registers the TypeScript plugin and parser only for some extensions; reuse them so
// the bans below also reach `.mts` files.
const nextTypescript = next.find((entry) => entry.plugins?.["@typescript-eslint"]);

const EFFECT_NAME = "/^use(Layout|Insertion)?Effect$/";

const EFFECT_MESSAGE =
  "Effects are for syncing with an external system only. Derive state while rendering, " +
  "handle events in their handlers, fetch with the generated query hooks, and subscribe " +
  "with useSyncExternalStore. If none fits, disable this line with the rule, a reason " +
  "and a ticket: `// eslint-disable-next-line no-restricted-syntax -- <reason> #<ticket>` (#166).";

const config = [
  {
    linterOptions: {
      reportUnusedDisableDirectives: "error",
    },
  },
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      "playwright-report/**",
      "test-results/**",
      "next-env.d.ts",
    ],
  },
  ...next,
  {
    files: ["src/**/*.{ts,tsx}", "e2e/**/*.ts", "*.ts"],
    plugins: {
      boundaries,
    },
    settings: {
      "boundaries/root-path": import.meta.dirname,
      "boundaries/elements": [
        {
          type: "feature",
          pattern: "src/features/*",
          capture: ["feature"],
        },
      ],
      "import/resolver": {
        typescript: {
          project: "./tsconfig.json",
        },
      },
    },
    rules: {
      "boundaries/dependencies": [
        "error",
        {
          default: "disallow",
          policies: [
            {
              from: { element: { type: "feature" } },
              allow: {
                to: {
                  element: {
                    type: "feature",
                    captured: {
                      feature: "{{ from.element.captured.feature }}",
                    },
                  },
                },
              },
            },
          ],
        },
      ],
    },
  },
  {
    // Agent mistakes become guards (#165, #166): effects and TypeScript silencers.
    files: ["src/**/*.{ts,tsx}", "e2e/**/*.ts", "e2e-level2/**/*.ts", "*.ts", "*.mts"],
    plugins: { "@typescript-eslint": nextTypescript.plugins["@typescript-eslint"] },
    languageOptions: { parser: nextTypescript.languageOptions.parser },
    rules: {
      // Selectors, not no-restricted-imports or no-restricted-properties: those reject
      // `import * as React` and only match an object named React.
      "no-restricted-syntax": [
        "error",
        ...[
          `ImportDeclaration[source.value='react'] > ImportSpecifier[imported.name=${EFFECT_NAME}]`,
          `ExportNamedDeclaration[source.value='react'] > ExportSpecifier[local.name=${EFFECT_NAME}]`,
          `MemberExpression[property.name=${EFFECT_NAME}]`,
          `MemberExpression[property.value=${EFFECT_NAME}]`,
          `VariableDeclarator[init.name='React'] > ObjectPattern > Property[key.name=${EFFECT_NAME}]`,
        ].map((selector) => ({ selector, message: EFFECT_MESSAGE })),
      ],
      "@typescript-eslint/ban-ts-comment": [
        "error",
        {
          "ts-ignore": true,
          "ts-nocheck": true,
          "ts-check": false,
          "ts-expect-error": { descriptionFormat: "^(:| --) .+ #\\d+$" },
        },
      ],
    },
  },
];

export default config;
