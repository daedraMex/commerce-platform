// @vitest-environment node
import { access, mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { ESLint } from "eslint";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

const consoleRoot = fileURLToPath(new URL("../..", import.meta.url));
const featureA = path.join(consoleRoot, "src/features/a/index.ts");
const featureB = path.join(consoleRoot, "src/features/b/index.ts");

const eslint = new ESLint({ cwd: consoleRoot });

let createdFeatureB = false;

const lint = async (filePath: string, source: string) => {
  const [result] = await eslint.lintText(source, { filePath });
  return result.messages;
};

beforeAll(async () => {
  try {
    await access(featureB);
  } catch {
    await mkdir(path.dirname(featureB), { recursive: true });
    await writeFile(featureB, "export const b = 1;\n", "utf-8");
    createdFeatureB = true;
  }
});

afterAll(async () => {
  if (createdFeatureB) {
    await rm(path.dirname(featureB), { recursive: true, force: true });
  }
});

describe("feature boundaries", () => {
  it("reports an error when a feature imports another feature", async () => {
    const aSource = 'import { b } from "@/features/b";\n\nexport const a = b;\n';
    const bSource = "export const b = 1;\n";

    const [aMessages, bMessages] = await Promise.all([
      lint(featureA, aSource),
      lint(featureB, bSource),
    ]);

    expect(bMessages).toEqual([]);
    expect(aMessages).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          ruleId: "boundaries/dependencies",
          severity: 2,
        }),
      ]),
    );
    expect(
      aMessages.some(
        (message) =>
          message.ruleId === "boundaries/dependencies" &&
          message.message.includes('feature="a"') &&
          message.message.includes('feature="b"'),
      ),
    ).toBe(true);
  });

  it("allows a feature to import a shared atom", async () => {
    const source =
      'import { Button } from "@/components/atoms/button";\n\nexport const A = Button;\n';

    const messages = await lint(featureA, source);

    expect(messages).toEqual([]);
  });
});
