"""Guards the migration chain itself (no database needed)."""
from __future__ import annotations

import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _revisions() -> dict[str, tuple[str, str | None]]:
    found: dict[str, tuple[str, str | None]] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        text = path.read_text()
        rev = re.search(r'^revision\s*=\s*"([^"]+)"', text, re.M)
        down = re.search(r'^down_revision\s*=\s*(None|"([^"]+)")', text, re.M)
        if not rev:
            continue
        assert rev.group(1) not in found, f"revision {rev.group(1)} is declared twice ({path.name})"
        found[rev.group(1)] = (path.name, down.group(2) if down else None)
    return found


def test_migration_revisions_are_unique_and_form_one_linear_chain():
    revs = _revisions()
    assert revs, "no migrations found"
    roots = [r for r, (_, down) in revs.items() if down is None]
    assert len(roots) == 1, f"expected exactly one base migration, found {roots}"
    parents = [down for _, down in revs.values() if down]
    assert len(parents) == len(set(parents)), "two migrations share a parent: the history has branched (multiple heads)"
    assert all(p in revs for p in parents), "a migration points at a missing parent"
    heads = [r for r in revs if r not in parents]
    assert len(heads) == 1, f"expected a single head, found {heads}"
