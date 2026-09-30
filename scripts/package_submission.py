#!/usr/bin/env python3
"""Build the public proposal attachment from an explicit allowlist.

Run again after editing proposal metadata. Private Judge data and its seed are
never included. This is an authoring tool, not part of candidate evaluation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FIXED_FILES = (
    ".gitignore", "proposal.md", "README.md", "SUBMISSION.md", "RUNBOOK.md",
    "DATA_SPEC.md", "data_manifest.json",
    "data/public/train.jsonl", "data/public/development.jsonl",
    "data/public/reference.jsonl", "data/baseline/train.jsonl",
    "data/baseline/provenance.jsonl", "data/baseline/manifest.json",
    "sources/open-jev/LICENSE",
)
PUBLIC_GLOBS = (
    "configs/*.json", "scripts/*.py", "evidence/*.json",
    "sources/open-jev/jev/*.py",
)


def main():
    paths = {ROOT / name for name in FIXED_FILES}
    for pattern in PUBLIC_GLOBS:
        paths.update(ROOT.glob(pattern))
    entries = {}
    for path in sorted(paths):
        name = path.relative_to(ROOT).as_posix()
        if path.is_symlink() or not path.is_file():
            raise ValueError("Missing or symlinked public asset: " + name)
        if not path.resolve().is_relative_to(ROOT) or "private" in Path(name).parts:
            raise ValueError("Non-public path in allowlist")
        entries[name] = path.read_bytes()
    manifest = {
        "schema_version": 1,
        "scope": "Public proposal attachment; private Judge data and seed excluded",
        "files": {name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                  for name, raw in sorted(entries.items())},
        "note": "This manifest excludes itself; it records integrity, not authenticity.",
    }
    entries["PUBLIC_PACKAGE_MANIFEST.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    target = ROOT / "dist" / "qwen-rsi-submission.zip"
    target.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 30, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, raw)
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None or set(archive.namelist()) != set(entries):
            raise ValueError("Archive integrity check failed")
        for name, raw in entries.items():
            if archive.read(name) != raw:
                raise ValueError("Archive byte mismatch")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".sha256").write_text(digest + "  " + target.name + "\n")
    print(json.dumps({"archive": str(target.relative_to(ROOT)),
                      "files": len(entries), "bytes": target.stat().st_size,
                      "sha256": digest, "private_data_included": False}, indent=2))


if __name__ == "__main__":
    main()
