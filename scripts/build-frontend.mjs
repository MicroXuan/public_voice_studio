import { createHash } from "node:crypto";
import { copyFile, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = path.join(root, "frontend");
const output = path.join(root, "dist");
const publicAssets = ["index.html", "styles.css", "app.js", "lib.js", "favicon.png", "wechat-qr.jpg"];

function assetVersion(content) {
  return createHash("sha256").update(content).digest("hex").slice(0, 12);
}

const rawApiBase = process.env.API_BASE_URL?.trim();
if (!rawApiBase) {
  throw new Error("API_BASE_URL is required to build the public frontend");
}

const apiUrl = new URL(rawApiBase);
if (!["http:", "https:"].includes(apiUrl.protocol)) {
  throw new Error("API_BASE_URL must use HTTP or HTTPS");
}
const normalizedPath = apiUrl.pathname.replace(/\/+$/, "");
const apiBase = `${apiUrl.origin}${normalizedPath}`;
const turnstileSiteKey = process.env.TURNSTILE_SITE_KEY?.trim() || "";

await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
await Promise.all(
  ["styles.css", "lib.js", "favicon.png", "wechat-qr.jpg"].map((name) => copyFile(path.join(source, name), path.join(output, name))),
);

const template = await readFile(path.join(source, "config.template.js"), "utf8");
const config = template
  .replace("__API_BASE_URL__", JSON.stringify(apiBase))
  .replace("__TURNSTILE_SITE_KEY__", JSON.stringify(turnstileSiteKey));
await writeFile(path.join(output, "config.js"), config, "utf8");

const [indexSource, styles, appSource, lib] = await Promise.all([
  readFile(path.join(source, "index.html"), "utf8"),
  readFile(path.join(source, "styles.css"), "utf8"),
  readFile(path.join(source, "app.js"), "utf8"),
  readFile(path.join(source, "lib.js"), "utf8"),
]);
const app = appSource.replace(
  'from "./lib.js";',
  `from "./lib.js?v=${assetVersion(lib)}";`,
);
await writeFile(path.join(output, "app.js"), app, "utf8");

const index = indexSource
  .replace("./styles.css", `./styles.css?v=${assetVersion(styles)}`)
  .replace("./config.js", `./config.js?v=${assetVersion(config)}`)
  .replace("./app.js", `./app.js?v=${assetVersion(app)}`);
await writeFile(path.join(output, "index.html"), index, "utf8");

process.stdout.write(`Built ${publicAssets.length + 1} public files in dist/\n`);
