// What the service worker may cache, and how its file is made from a finished build. Pure (no file access) so vitest can
// test it; vite-plugin-shell.ts does the reading, hashing and writing.

/** Public shell files only, relative to the build directory. A JS/CSS file counts only if its name carries a content hash. */
const SHELL_FILE = /^(index\.html|manifest\.webmanifest|icons\/[\w.-]+\.png|assets\/[\w.]+-[\w-]{6,}\.(js|css))$/;

export function shellUrls(files: string[]): string[] {
  return files.filter((f) => SHELL_FILE.test(f)).map((f) => `/${f}`).sort();
}

export function renderWorker(template: string, buildId: string, urls: string[]): string {
  if (!/^[0-9a-f]{12}$/.test(buildId)) throw new Error("bad build id");
  if (!urls.includes("/index.html")) throw new Error("the build has no index.html");
  if (!urls.some((u) => u.endsWith(".js"))) throw new Error("the build has no JavaScript");
  if (urls.some((u) => u.startsWith("/api/"))) throw new Error("the API is never precached");
  if (!template.includes('"__BUILD_ID__"') || !template.includes("__PRECACHE__")) throw new Error("worker template placeholders are missing");
  return template.replace('"__BUILD_ID__"', () => JSON.stringify(buildId)).replace("__PRECACHE__", () => JSON.stringify(urls));
}
