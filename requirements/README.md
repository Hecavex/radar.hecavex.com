# Production Python automation locks

These files support HECAVEX's scheduled `radar.hecavex.com` workflows and CI; they are not a general installation matrix.

The two hash-locked requirement sets target Python 3.12 on the Ubuntu GitHub Actions runners:

- `automation-runtime-py312.lock` is the minimal environment used by scheduled collectors and the snapshot publisher.
- `automation-ci-py312.lock` adds linting and type-checking tools for CI.

The checked-out HECAVEX Radar package is installed separately with dependency resolution and build isolation disabled. Its direct and build dependencies are therefore supplied by the reviewed lock before the package is built.

To refresh a lock, run `uv pip compile` 0.12.5 with `--python-version 3.12`, `--python-platform x86_64-unknown-linux-gnu`, and `--generate-hashes`, then run `pip-audit` against both resulting files and the full project checks. Keep the `.in` files and `pyproject.toml` aligned in the same change.

The reproducible entry point is `python scripts/python-locks.py --update`. It refreshes both Linux-targeted locks with the pinned compiler and checks every project/runtime/tooling pin. Run `python scripts/python-locks.py` for the read-only check, which CI executes before installing anything. A dependency PR that only changes manifests is incomplete and must include the regenerated locks before merge. Hash-verified installation is never disabled to accommodate an update.

The September maintenance update adopts websockets 17.1, hypothesis 6.167.1 and ruff 0.16.5. It deliberately retains stix2-validator 3.2.0 because the 3.3.1 wheel lacks required bundled schemas. Dependabot ignores only that known-broken version, not future versions. A green update must pass actual STIX validation as well as installation.
