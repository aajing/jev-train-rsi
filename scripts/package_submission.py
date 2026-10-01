#!/usr/bin/env python3
"""Build the public proposal attachment from an explicit allowlist.

Run again after editing proposal metadata. The contributor-authorized evaluation
files are included through an exact allowlist, without encryption. This is an
authoring tool, not part of candidate evaluation or the candidate Work image.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FIXED_FILES = (
    ".gitignore", "proposal.md", "README.md", "SUBMISSION.md", "RUNBOOK.md",
    "DATA_SPEC.md", "EVALUATION_ASSETS.md", "data_manifest.json",
    "data/public/train.jsonl", "data/public/development.jsonl",
    "data/public/reference.jsonl", "data/baseline/train.jsonl",
    "data/baseline/provenance.jsonl", "data/baseline/manifest.json",
    "sources/open-jev/LICENSE",
)
PUBLIC_GLOBS = (
    "configs/*.json", "scripts/*.py", "evidence/*.json",
    "sources/open-jev/jev/*.py",
)
AUTHORIZED_EVALUATION_FILES = (
    "data/private/judge.jsonl",
    "data/private/generator_seed.json",
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
    for name in AUTHORIZED_EVALUATION_FILES:
        published = ROOT / "evaluation-assets" / name
        path = published if published.is_file() else ROOT / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT):
            raise ValueError("Missing or unsafe authorized evaluation asset: " + name)
        entries[name] = path.read_bytes()
    delivery_path = ROOT / "evaluation-assets" / "EVALUATION_ASSETS_MANIFEST.json"
    entries["EVALUATION_ASSETS_MANIFEST.json"] = delivery_path.read_bytes()
    delivery = json.loads(entries["EVALUATION_ASSETS_MANIFEST.json"])
    if set(delivery["files"]) != set(AUTHORIZED_EVALUATION_FILES):
        raise ValueError("Evaluation delivery allowlist mismatch")
    for name in AUTHORIZED_EVALUATION_FILES:
        expected = delivery["files"][name]
        if (len(entries[name]) != expected["bytes"] or
                hashlib.sha256(entries[name]).hexdigest() != expected["sha256"]):
            raise ValueError("Evaluation asset commitment mismatch: " + name)
    manifest = {
        "schema_version": 1,
        "project": "jev-train-rsi",
        "scope": "Public proposal attachment including the original evaluation data and seed",
        "evaluation_asset_distribution": "Public, unencrypted, explicitly authorized by the contributor; exclude from Work at runtime",
        "files": {name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                  for name, raw in sorted(entries.items())},
        "note": "This manifest excludes itself; it records integrity, not authenticity.",
    }
    entries["PUBLIC_PACKAGE_MANIFEST.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    target = ROOT / "dist" / "jev-train-rsi-submission.zip"
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
                      "sha256": digest, "evaluation_data_included": True,
                      "encryption": "none"}, indent=2))


if __name__ == "__main__":
    main()
