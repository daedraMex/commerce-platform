import next from "eslint-config-next/core-web-vitals";
import boundaries from "eslint-plugin-boundaries";

const EFFECT_MESSAGE =
  "Effects are for syncing with an external system only. Derive state while rendering, " +
  "handle events in their handlers, fetch with the generated query hooks, and subscribe " +
  "with useSyncExternalStore. If none fits, disable this line with the rule, a reason " +
  "and a ticket: `// eslint-disable-next-line <rule> -- <reason> #<ticket>` (#166).";

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
    files: ["src/**/*.{ts,tsx}", "e2e/**/*.ts", "*.ts"],
    rules: {
      // A selector, not no-restricted-imports: that rule also rejects `import * as React`.
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "ImportDeclaration[source.value='react'] > ImportSpecifier[imported.name=/^use(Layout)?Effect$/]",
          message: EFFECT_MESSAGE,
        },
      ],
      "no-restricted-properties": [
        "error",
        { object: "React", property: "useEffect", message: EFFECT_MESSAGE },
        { object: "React", property: "useLayoutEffect", message: EFFECT_MESSAGE },
      ],
      "@typescript-eslint/ban-ts-comment": [
        "error",
        {
          "ts-ignore": true,
          "ts-nocheck": true,
          "ts-check": false,
          "ts-expect-error": { descriptionFormat: "^: .+ #\\d+$" },
          minimumDescriptionLength: 10,
        },
      ],
    },
  },
];

export default config;
