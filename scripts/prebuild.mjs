// Split latest.json into per-area files before a web build, so Vercel serves them.
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const py = existsSync(resolve(root, ".venv/bin/python")) ? resolve(root, ".venv/bin/python") : "python3";
execFileSync(py, [resolve(root, "scripts/split_forecast.py")], { stdio: "inherit" });
