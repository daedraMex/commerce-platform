import { defineConfig } from "orval";

export default defineConfig({
  api: {
    input: "./openapi.json",
    output: {
      target: "./src/generated/api.ts",
      schemas: "./src/generated/model",
      client: "react-query",
      httpClient: "axios",
      mock: {
        generators: [{ type: "msw", useExamples: true }],
      },
      clean: true,
      formatter: "prettier",
      override: {
        mutator: {
          path: "./src/axios.ts",
          name: "apiClient",
        },
      },
    },
  },
});
