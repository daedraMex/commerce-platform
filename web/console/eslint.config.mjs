import next from "eslint-config-next/core-web-vitals";
import boundaries from "eslint-plugin-boundaries";

const config = [
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
];

export default config;
