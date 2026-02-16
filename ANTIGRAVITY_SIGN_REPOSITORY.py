#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ANTIGRAVITY_SIGN_REPOSITORY.py
==============================

Purpose:
Create a deterministic authorship and provenance signature
for the current repository state.

This script does NOT encrypt or obfuscate.
It records traceable evidence.
"""

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(".")
OUTPUT_FILE = "artifact_manifest.json"

INCLUDE_EXTENSIONS = {
    ".py", ".md", ".txt", ".json"
}

EXCLUDE_DIRS = {
    ".git", "__pycache__", ".venv", "node_modules"
}


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_artifacts():
    artifacts = []
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for name in files:
            path = Path(root).relative_to(REPO_ROOT) / name
            if path.suffix.lower() in INCLUDE_EXTENSIONS:
                if str(path) == OUTPUT_FILE:
                    continue
                artifacts.append({
                    "path": str(path),
                    "sha256": hash_file(REPO_ROOT / path)
                })
    return sorted(artifacts, key=lambda x: x["path"])


def main():
    manifest = {
        "author": "José de Ávila",
        "tool": "Antigravity",
        "purpose": "Repository provenance and authorship signature",
        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "hash_algorithm": "SHA-256",
        "artifacts": collect_artifacts()
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"[OK] Repository signed.")
    print(f"[OK] Manifest written to {OUTPUT_FILE}")
    print(f"[INFO] Artifacts signed: {len(manifest['artifacts'])}")


if __name__ == "__main__":
    main()
