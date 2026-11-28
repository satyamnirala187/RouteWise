// Emits /sw.js after a production build, from the files the build actually wrote (never a hand-kept list).
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Plugin } from "vite";
import { renderWorker, shellUrls } from "./src/sw/generate.ts";

const TEMPLATE = fileURLToPath(new URL("./src/sw/worker.template.js", import.meta.url));

function listFiles(dir: string, base = dir): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    return statSync(full).isDirectory() ? listFiles(full, base) : [path.relative(base, full).split(path.sep).join("/")];
  });
}

/** Writes sw.js into a finished build directory. The build id covers the worker's own code and every cached file's bytes, so
 * any change to the shell gives the browser a different worker, and an unchanged shell never does. */
export function emitWorker(outDir: string): { buildId: string; urls: string[]; notCached: string[] } {
  const all = listFiles(outDir).filter((f) => f !== "sw.js");
  const urls = shellUrls(all);
  const template = readFileSync(TEMPLATE, "utf8");
  const hash = createHash("sha256").update(template);
  for (const url of urls) hash.update("\0" + url + "\0").update(readFileSync(path.join(outDir, url)));
  const buildId = hash.digest("hex").slice(0, 12);
  writeFileSync(path.join(outDir, "sw.js"), renderWorker(template, buildId, urls));
  return { buildId, urls, notCached: all.filter((f) => !urls.includes(`/${f}`)) };
}

export function shellWorker(): Plugin {
  let outDir = "";
  return {
    name: "routewise-shell-worker",
    apply: "build",
    configResolved(config) { outDir = path.resolve(config.root, config.build.outDir); },
    closeBundle() {
      const { buildId, urls, notCached } = emitWorker(outDir);
      console.log(`shell worker ${buildId}: ${urls.length} public files precached${notCached.length ? `; not cached: ${notCached.join(", ")}` : ""}`);
    },
  };
}
