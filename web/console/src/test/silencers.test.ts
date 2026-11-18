// @vitest-environment node
import { describe, expect, it } from "vitest";

import { findBareSilencers } from "../../scripts/check-silencers.mjs";

describe("eslint-disable needs a rule, a reason and a ticket (#166)", () => {
  it("accepts a named rule with a reason and a ticket", () => {
    const source = "// eslint-disable-next-line no-restricted-properties -- writes <html> #166\nx();\n";

    expect(findBareSilencers(source, "a.tsx")).toEqual([]);
  });

  it.each([
    ["no rule", "/* eslint-disable */\n"],
    ["no reason", "// eslint-disable-next-line no-console\n"],
    ["no ticket", "// eslint-disable-line no-console -- just because\n"],
  ])("rejects %s", (_case, source) => {
    expect(findBareSilencers(source, "a.tsx")).toHaveLength(1);
  });

  it("ignores the same text inside a string", () => {
    const source = 'const example = "// eslint-disable-next-line no-console";\n';

    expect(findBareSilencers(source, "a.ts")).toEqual([]);
  });
});
