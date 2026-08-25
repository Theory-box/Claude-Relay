#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

const [htmlPath, nagaPathArg] = process.argv.slice(2);
if (!htmlPath) {
  console.error("Usage: node validate-string-engine-wgsl.mjs <string-engine.html> [naga-command]");
  process.exit(2);
}

const naga = nagaPathArg || "naga";
const html = fs.readFileSync(htmlPath, "utf8");
const shaderNames = ["WGSL_INT", "WGSL_CON", "WGSL_REN"];
const tempDir = fs.mkdtempSync(path.join(process.cwd(), ".string-engine-wgsl-"));
let failed = false;

try {
  for (const name of shaderNames) {
    const pattern = new RegExp("const\\s+" + name + "\\s*=\\s*`([\\s\\S]*?)`;");
    const match = html.match(pattern);
    if (!match) {
      console.error(`FAIL ${name}: shader template not found`);
      failed = true;
      continue;
    }

    const input = path.join(tempDir, `${name}.wgsl`);
    const cliInput = path.relative(process.cwd(), input);
    fs.writeFileSync(input, match[1], "utf8");
    const result = spawnSync(naga, ["--input-kind", "wgsl", cliInput], {
      encoding: "utf8",
      shell: process.platform === "win32",
    });
    const details = `${result.stdout || ""}${result.stderr || ""}`.trim();
    if (result.status === 0) {
      console.log(`PASS ${name} (${match[1].split("\n").length} lines)`);
    } else {
      console.error(`FAIL ${name} (exit ${result.status ?? "spawn error"})`);
      if (details) console.error(details);
      failed = true;
    }
  }
} finally {
  fs.rmSync(tempDir, { recursive: true, force: true });
}

process.exit(failed ? 1 : 0);
