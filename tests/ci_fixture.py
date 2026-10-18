"""Guard for tests that need the regenerated CI data fixture.

The `data/` and `public/data/` copies tracked on `main` are a frozen 2026-09-07 snapshot
(the dev fixture and the `data_branch bootstrap` seed). Source code has moved on since, so
tests that check freshly derived artifacts against the working tree only hold after CI's
fixture steps (`data_branch materialize-fixture`, `offline_publication`,
`quality_artifacts`). Locally, an unmodified frozen copy skips them with that reason;
under CI they always run, so they can never be skipped silently there.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

FROZEN_COPY_REASON = (
    "data/ and public/data/ are the unmodified frozen 2026-09-07 copy tracked on main, not the "
    "regenerated CI fixture. In a throwaway checkout run: python -m hecavex_radar.data_branch "
    "materialize-fixture --repository . --revision <ci.yml revision>; python -m "
    "hecavex_radar.offline_publication; python -m hecavex_radar.quality_artifacts"
)


def require_ci_fixture(root: Path) -> None:
    if os.environ.get("CI"):
        return
    changed = subprocess.run(  # noqa: S603 - fixed git arguments on the trusted source tree.
        ["git", "-C", str(root), "status", "--porcelain", "--", "data", "public/data"],  # noqa: S607
        check=True, capture_output=True, text=True,
    ).stdout
    if not changed.strip():
        pytest.skip(FROZEN_COPY_REASON)
