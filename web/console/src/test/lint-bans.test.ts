// @vitest-environment node
import path from "node:path";
import { fileURLToPath } from "node:url";

import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

const consoleRoot = fileURLToPath(new URL("../..", import.meta.url));
const filePath = path.join(consoleRoot, "src/features/photos/planted.tsx");
const eslint = new ESLint({ cwd: consoleRoot });

const ruleIds = async (source: string, file = filePath) => {
  const [result] = await eslint.lintText(source, { filePath: file });
  return result.messages.map((message) => message.ruleId ?? message.message);
};

describe("useEffect is banned (#166)", () => {
  it("rejects the named import", async () => {
    expect(await ruleIds('import { useEffect } from "react";\nuseEffect(() => {}, []);\n')).toContain(
      "no-restricted-syntax",
    );
  });

  it("rejects useLayoutEffect too", async () => {
    expect(await ruleIds('import { useLayoutEffect } from "react";\nuseLayoutEffect(() => {});\n')).toContain(
      "no-restricted-syntax",
    );
  });

  it("rejects React.useEffect and destructuring from React", async () => {
    const source =
      'import * as React from "react";\nReact.useEffect(() => {}, []);\nconst { useEffect } = React;\nuseEffect(() => {});\n';
    const ids = await ruleIds(source);

    expect(ids.filter((id) => id === "no-restricted-syntax")).toHaveLength(2);
  });

  it("allows useSyncExternalStore and useMemo", async () => {
    const source =
      'import * as React from "react";\nexport const a = React.useMemo;\nexport const b = React.useSyncExternalStore;\n';

    expect(await ruleIds(source)).toEqual([]);
  });
});

describe("TypeScript silencers (#166)", () => {
  it("rejects @ts-ignore and @ts-nocheck", async () => {
    const ids = await ruleIds("// @ts-ignore\nexport const a: number = 1;\n");

    expect(ids).toContain("@typescript-eslint/ban-ts-comment");
  });

  it("rejects @ts-expect-error without a description", async () => {
    const ids = await ruleIds("// @ts-expect-error\nexport const a: number = 1;\n");

    expect(ids).toContain("@typescript-eslint/ban-ts-comment");
  });

  it("reports a disable directive that silences nothing", async () => {
    const ids = await ruleIds(
      "// eslint-disable-next-line no-console -- not needed #166\nexport const a = 1;\n",
    );

    expect(ids.join(" ")).toMatch(/Unused eslint-disable directive/);
  });
});

describe("@ts-expect-error names a ticket (#166)", () => {
  it("accepts a reason with a ticket", async () => {
    const ids = await ruleIds(
      "// @ts-expect-error: the generated type lags the schema #166\nexport const a: number = '1';\n",
    );

    expect(ids).not.toContain("@typescript-eslint/ban-ts-comment");
  });

  it("rejects a reason without a ticket", async () => {
    const ids = await ruleIds(
      "// @ts-expect-error: the generated type lags the schema\nexport const a: number = '1';\n",
    );

    expect(ids).toContain("@typescript-eslint/ban-ts-comment");
  });
});


describe("ways around the effect ban (#166 review)", () => {
  it.each([
    ["a re-export", 'export { useEffect } from "react";\n'],
    ["another namespace name", 'import * as R from "react";\nR.useEffect(() => {}, []);\n'],
    ["a computed member", 'import * as React from "react";\nReact["useEffect"](() => {});\n'],
    ["useInsertionEffect", 'import { useInsertionEffect } from "react";\nuseInsertionEffect(() => {});\n'],
  ])("rejects %s", async (_case, source) => {
    expect(await ruleIds(source)).toContain("no-restricted-syntax");
  });

  it.each([
    ["e2e-level2/planted.ts", "// @ts-ignore\nexport const a: number = 1;\n"],
    ["vitest.planted.mts", "// @ts-ignore\nexport const a: number = 1;\n"],
  ])("lints %s", async (file, source) => {
    expect(await ruleIds(source, path.join(consoleRoot, file))).toContain(
      "@typescript-eslint/ban-ts-comment",
    );
  });

  it("accepts the -- form of @ts-expect-error too", async () => {
    const ids = await ruleIds(
      "// @ts-expect-error -- the generated type lags the schema #166\nexport const a: number = '1';\n",
    );

    expect(ids).not.toContain("@typescript-eslint/ban-ts-comment");
  });
});
