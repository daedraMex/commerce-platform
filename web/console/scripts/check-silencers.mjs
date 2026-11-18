#!/usr/bin/env node
// Every eslint-disable comment names its rules, a reason and a ticket (#166):
//   // eslint-disable-next-line <rule> -- <reason> #<ticket>
// so a workaround stays visible in review instead of hiding behind a bare disable.
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";

const DIRECTIVE_RE = /^\s*eslint-disable(?:-next-line|-line)?\b(?<rest>.*)$/s;
const RULES_AND_REASON_RE = /^\s+\S.*?\s--\s+\S/s;
const TICKET_RE = /#\d+/;
const SOURCE_EXTENSIONS = new Set([".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]);
const SKIPPED_DIRS = new Set(["node_modules", ".next", "playwright-report", "test-results"]);

function comments(source, fileName) {
  // The full parser, not a bare scanner: only it tells a regex or a string from a comment.
  const kind = fileName.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const sourceFile = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, kind);
  const ranges = new Map();
  const collect = (node) => {
    for (const range of [
      ...(ts.getLeadingCommentRanges(source, node.getFullStart()) ?? []),
      ...(ts.getTrailingCommentRanges(source, node.getEnd()) ?? []),
    ]) {
      ranges.set(range.pos, range);
    }
    for (const child of node.getChildren(sourceFile)) collect(child);
  };
  collect(sourceFile);
  return [...ranges.values()].map((range) => {
    const text = source.slice(range.pos, range.end);
    const body = text.startsWith("//") ? text.slice(2) : text.slice(2, -2);
    return { line: sourceFile.getLineAndCharacterOfPosition(range.pos).line + 1, body };
  });
}

/** Bare disable comments in one file: no rule, no `-- reason` or no ticket. */
export function findBareSilencers(source, fileName) {
  return comments(source, fileName)
    .map(({ line, body }) => ({ line, body, match: DIRECTIVE_RE.exec(body) }))
    .filter(({ match }) => match !== null)
    .filter(({ match }) => {
      const rest = match.groups.rest;
      return !RULES_AND_REASON_RE.test(rest) || !TICKET_RE.test(rest);
    })
    .map(({ line, body }) => `${fileName}:${line} ${body.trim()}`);
}

function* sourceFiles(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (!SKIPPED_DIRS.has(entry.name)) yield* sourceFiles(path.join(dir, entry.name));
    } else if (SOURCE_EXTENSIONS.has(path.extname(entry.name))) {
      yield path.join(dir, entry.name);
    }
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const bare = [...sourceFiles(root)].flatMap((file) =>
    findBareSilencers(readFileSync(file, "utf-8"), path.relative(root, file)),
  );
  if (bare.length > 0) {
    console.error("Write `// eslint-disable-next-line <rule> -- <reason> #<ticket>`:");
    for (const line of bare) console.error(`  ${line}`);
    process.exit(1);
  }
}
