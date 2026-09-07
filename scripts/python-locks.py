"""Check or explicitly regenerate both reviewed Linux/Python 3.12 locks."""

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = "CPython 3.12 on GitHub Actions Linux x86_64"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true")
    options = parser.parse_args()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = project["project"]["dependencies"] + project["build-system"]["requires"]
    tooling = project["project"]["optional-dependencies"]["dev"]
    for name, pins in (("runtime", runtime), ("ci", runtime + tooling)):
        source = ROOT / "requirements" / f"automation-{name}.in"
        lock = ROOT / "requirements" / f"automation-{name}-py312.lock"
        direct = set(re.findall(r"^([a-z0-9-]+==[^\s#]+)$", source.read_text(encoding="utf-8"), re.MULTILINE))
        if direct != set(runtime if name == "runtime" else tooling):
            raise SystemExit(f"{source.name} does not exactly match its pyproject.toml dependency group.")
        if options.update:
            version = subprocess.check_output([sys.executable, "-m", "uv", "--version"], text=True)
            if not version.startswith("uv 0.12.5 "):
                raise SystemExit("Use reviewed uv 0.12.5 to regenerate automation locks.")
            subprocess.run([
                sys.executable, "-m", "uv", "pip", "compile", str(source), "--python-version", "3.12",
                "--python-platform", "x86_64-unknown-linux-gnu", "--generate-hashes",
                "--custom-compile-command", f"python scripts/python-locks.py --update ({TARGET})",
                "--output-file", str(lock), "--quiet",
            ], check=True, cwd=ROOT)
        body = lock.read_text(encoding="utf-8")
        missing = [pin for pin in pins if not re.search(rf"^{re.escape(pin)} \\", body, re.MULTILINE)]
        if missing or TARGET not in body:
            raise SystemExit(f"{lock.name} is inconsistent. Run python scripts/python-locks.py --update. Missing: {missing}")
    print("Both Linux/Python 3.12 automation locks match the direct project pins.")


if __name__ == "__main__":
    main()
