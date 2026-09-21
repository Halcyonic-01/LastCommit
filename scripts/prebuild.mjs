// Split latest.json into per-area files before a web build, so the host serves them.
// forecast/area/ is gitignored (1,127 files would bury every nightly commit), so this
// step is what puts them in dist — it is not optional.
//
// Picking the interpreter is the fiddly part. Vercel's build image is uv-managed, so a
// plain `pip install` there fails with PEP 668 "externally-managed-environment"; the
// build therefore creates a .venv, which is the first thing checked for below.
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const script = resolve(root, "scripts/split_forecast.py");

// In order: an explicit override, a project venv (local dev and the CI build both make
// one), then whatever python is on PATH.
const candidates = [
  process.env.PYTHON,
  resolve(root, ".venv/bin/python"),
  resolve(root, ".venv/Scripts/python.exe"),   // Windows layout
  "python3",
  "python",
].filter(Boolean);

function canImportDeps(py) {
  try {
    execFileSync(py, ["-c", "import jsonschema, referencing"], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

const py = candidates.find((c) => (c === "python3" || c === "python" || existsSync(c)) && canImportDeps(c));

if (!py) {
  console.error(
    "\nprebuild: no Python with jsonschema + referencing.\n" +
    "  scripts/split_forecast.py validates every area file against the frozen schema\n" +
    "  before writing it, so the build cannot skip it.\n\n" +
    "  Local:  python3 -m venv .venv && .venv/bin/pip install -r requirements-build.txt\n" +
    "  CI:     same, or set PYTHON to an interpreter that already has them\n" +
    `  Tried:  ${candidates.join(", ")}\n`
  );
  process.exit(1);
}

execFileSync(py, [script], { stdio: "inherit" });
