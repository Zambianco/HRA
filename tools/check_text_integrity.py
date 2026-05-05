#!/usr/bin/env python3
"""
Fail if repository text files are not UTF-8 or contain common mojibake tokens.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

TEXT_EXTENSIONS = {
    ".py",
    ".html",
    ".htm",
    ".css",
    ".js",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".json",
    ".ini",
    ".cfg",
    ".csv",
}

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
}

MOJIBAKE_PATTERNS = [
    re.compile(r"\u00c3[\u0080-\u00bf]"),  # Ã + continuation-byte-like char
    re.compile(r"\u00c2[\u0080-\u00bf]"),  # Â + continuation-byte-like char
    re.compile(r"\u00e2\u20ac"),  # â€
    re.compile(r"\u00ef\u00bb\u00bf"),  # ï»¿
]


def should_check(path: Path) -> bool:
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return False
    return not any(part in SKIP_DIRS for part in path.parts)


def main() -> int:
    root = Path(".")
    utf8_errors: list[str] = []
    mojibake_hits: list[str] = []

    for path in root.rglob("*"):
        if not path.is_file() or not should_check(path):
            continue

        rel = path.as_posix()
        if rel == "tools/check_text_integrity.py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            utf8_errors.append(rel)
            continue

        for pattern in MOJIBAKE_PATTERNS:
            if pattern.search(text):
                mojibake_hits.append(f"{rel}: pattern '{pattern.pattern}'")
                break

    if utf8_errors or mojibake_hits:
        print("Text integrity check failed.")
        if utf8_errors:
            print("\nNon-UTF-8 files:")
            for item in utf8_errors:
                print(f" - {item}")
        if mojibake_hits:
            print("\nPossible mojibake:")
            for item in mojibake_hits:
                print(f" - {item}")
        return 1

    print("Text integrity check passed (UTF-8 + no known mojibake tokens).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
