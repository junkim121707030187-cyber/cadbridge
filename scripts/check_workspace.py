#!/usr/bin/env python3
"""문서·협업 패키지 정적 검사. CAD/API 실행을 검사하거나 보증하지 않는다."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import unquote, urlsplit

TEXT_SUFFIXES = {".md", ".json", ".py", ".yaml", ".yml", ".toml", ".txt", ".ini", ".cfg"}
TEXT_NAMES = {".gitignore", ".gitattributes", ".editorconfig", ".env.example"}
FORBIDDEN_DIRS = {".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "runtime-logs", ".tmp"}
CONFLICT = re.compile(r"^(?:<{7}(?: .*)?|={7}|>{7}(?: .*)?)$", re.MULTILINE)
REQ = re.compile(r"\bR-\d{2}\b")
PRIVATE_PATH = re.compile(r"(?:[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/][^\s\"'<>]+|/(?:home|Users)/[^\s\"'<>]+|/workspace" + r"/scratch/[^\s\"'<>]+)", re.IGNORECASE)
PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")
KNOWN_TOKEN = re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-(?:proj-)?[A-Za-z0-9_-]{32,}|AKIA[0-9A-Z]{16})")
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


def unfenced(text: str) -> str:
    """예제 코드의 링크·제목을 문서 탐색 대상으로 해석하지 않는다."""
    result, opened = [], None
    for line in text.splitlines():
        match = FENCE.match(line)
        if match:
            token = match.group(1)
            if opened is None:
                opened = token
            elif token[0] == opened[0] and len(token) >= len(opened):
                opened = None
            result.append("")
        else:
            result.append(line if opened is None else "")
    return "\n".join(result)


def anchors(text: str) -> set[str]:
    text = unfenced(text)
    found = set(re.findall(r"\b(?:id|name)=[\"']([^\"']+)[\"']", text))
    counts: dict[str, int] = {}
    lines = text.splitlines()
    headings = []
    for index, line in enumerate(lines):
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if heading:
            headings.append(heading.group(1))
        elif index and re.fullmatch(r"\s{0,3}(?:=+|-+)\s*", line) and lines[index - 1].strip():
            headings.append(lines[index - 1].strip())
    for heading in headings:
        heading = re.sub(r"!?\[([^\]]+)\]\([^)]*\)", r"\1", heading)
        heading = re.sub(r"<[^>]+>", "", heading).lower()
        slug = re.sub(r"[^\w\- ]", "", heading).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        found.add(slug if count == 0 else f"{slug}-{count}")
    return found


def markdown_targets(text: str) -> list[str]:
    text = unfenced(text)
    definitions: dict[str, str] = {}
    for match in re.finditer(r"^\s{0,3}\[([^\]]+)\]:\s*(<[^>]+>|\S+)", text, re.MULTILINE):
        definitions[match.group(1).casefold()] = match.group(2).strip("<>")
    targets = list(definitions.values())
    # 괄호가 포함된 상대 경로를 읽고 공백 뒤의 링크 제목은 제외한다.
    for match in re.finditer(r"!?\[[^\]\n]*\]\(", text):
        index, start, depth = match.end(), match.end(), 1
        while index < len(text) and depth:
            char = text[index]
            if char == "\\":
                index += 2
                continue
            depth += (char == "(") - (char == ")")
            if depth:
                index += 1
        if depth == 0:
            target = text[start:index].strip()
            if target.startswith("<") and ">" in target:
                target = target[1:target.index(">")]
            else:
                target = re.split(r"\s+[\"']", target, maxsplit=1)[0]
            if target:
                targets.append(target)
    for match in re.finditer(r"!?\[([^\]\n]+)\]\[([^\]\n]*)\]", text):
        label = (match.group(2) or match.group(1)).casefold()
        if label in definitions:
            targets.append(definitions[label])
        else:
            targets.append(f"__undefined_reference__/{label}")
    return targets


def contained(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
        return True
    except ValueError:
        return False


def check(root: Path, verify_manifest: bool) -> tuple[list[str], dict[str, int]]:
    errors: list[str] = []
    stats = {"files": 0, "text_files": 0, "relative_links": 0, "manifest_entries": 0}
    files: dict[str, Path] = {}
    texts: dict[str, str] = {}
    for directory, dirs, names in os.walk(root):
        relative_dir = Path(directory).relative_to(root)
        # Git's internal objects/config are not package payloads.
        dirs[:] = sorted(d for d in dirs if d != ".git")
        for dirname in list(dirs):
            candidate = Path(directory) / dirname
            rel = (relative_dir / dirname).as_posix()
            if candidate.is_symlink():
                errors.append(f"{rel}: symbolic directory is not allowed")
                dirs.remove(dirname)
            elif dirname in FORBIDDEN_DIRS:
                errors.append(f"{rel}: generated/cache directory must be outside the bundle")
                dirs.remove(dirname)
        for name in sorted(names):
            path = Path(directory) / name
            rel = (relative_dir / name).as_posix()
            if path.is_symlink():
                errors.append(f"{rel}: symbolic file is not allowed")
                continue
            files[rel] = path
            stats["files"] += 1
            if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
                errors.append(f"{rel}: secret configuration must not be in the bundle")
            if path.suffix in {".pyc", ".pyo"}:
                errors.append(f"{rel}: generated bytecode must not be in the bundle")
            try:
                raw = path.read_bytes()
            except OSError:
                errors.append(f"{rel}: cannot read file")
                continue
            # ASCII 비밀 패턴은 CAD 등 비텍스트 파일에도 적용한다.
            scan = raw.decode("latin-1")
            for pattern, message in ((PRIVATE_KEY, "private-key material"), (KNOWN_TOKEN, "credential-shaped value")):
                if pattern.search(scan):
                    errors.append(f"{rel}: {message} detected (value redacted)")
            if path.suffix.lower() not in TEXT_SUFFIXES and name not in TEXT_NAMES:
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                errors.append(f"{rel}: cannot read valid UTF-8")
                continue
            texts[rel] = text
            stats["text_files"] += 1
            if text.startswith("\ufeff"):
                errors.append(f"{rel}: UTF-8 BOM is not allowed")
            if CONFLICT.search(text):
                errors.append(f"{rel}: unresolved merge conflict marker")
            for pattern, message in ((PRIVATE_PATH, "personal absolute path"),):
                if pattern.search(text):
                    errors.append(f"{rel}: {message} detected (value redacted)")
            if path.suffix.lower() == ".json":
                try:
                    json.loads(text)
                except json.JSONDecodeError as error:
                    errors.append(f"{rel}:{error.lineno}: invalid JSON")
    requirements = texts.get("docs/REQUIREMENTS.md", "")
    defined = set(re.findall(r"^\|\s*(R-\d{2})\s*\|", requirements, re.MULTILINE))
    expected = {f"R-{number:02d}" for number in range(1, 13)}
    if not expected <= defined:
        errors.append("docs/REQUIREMENTS.md: missing required definitions: " + ", ".join(sorted(expected - defined)))
    for rel, text in texts.items():
        if rel == "BUNDLE_MANIFEST.json":
            continue
        for unknown in sorted(set(REQ.findall(text)) - defined):
            errors.append(f"{rel}: undefined requirement {unknown}")
        if not rel.endswith(".md"):
            continue
        for target in markdown_targets(text):
            try:
                split = urlsplit(target)
            except ValueError:
                errors.append(f"{rel}: malformed link target")
                continue
            if split.scheme or split.netloc:
                continue
            stats["relative_links"] += 1
            target_path = unquote(split.path)
            destination = (files[rel].parent / target_path).resolve() if target_path else files[rel]
            if not contained(destination, root):
                errors.append(f"{rel}: link escapes package root")
                continue
            if not destination.exists():
                errors.append(f"{rel}: missing link target {target}")
                continue
            if split.fragment and destination.suffix.lower() == ".md":
                fragment = unquote(split.fragment)
                linked = texts.get(destination.relative_to(root).as_posix(), "")
                if fragment not in anchors(linked):
                    errors.append(f"{rel}: missing Markdown anchor {target}")
    if verify_manifest:
        manifest_path = root / "BUNDLE_MANIFEST.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            entries = manifest["files"]
            if not isinstance(entries, list):
                raise ValueError("files must be a list")
        except (OSError, ValueError, KeyError, TypeError):
            errors.append("BUNDLE_MANIFEST.json: missing or invalid manifest")
            entries = []
        recorded: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                errors.append("BUNDLE_MANIFEST.json: malformed file entry")
                continue
            rel = entry["path"]
            # The original v1 handoff also hashes the sibling recovery JSON.
            external_recovery = rel == "../seed-docs.json"
            if not external_recovery and (PurePosixPath(rel).is_absolute() or ".." in PurePosixPath(rel).parts or "\\" in rel):
                errors.append("BUNDLE_MANIFEST.json: unsafe file path")
                continue
            if rel in recorded:
                errors.append(f"BUNDLE_MANIFEST.json: duplicate entry {rel}")
                continue
            recorded.add(rel)
            path = root / rel
            if rel == "BUNDLE_MANIFEST.json":
                errors.append("BUNDLE_MANIFEST.json: cannot hash itself")
                continue
            try:
                data = path.read_bytes()
            except OSError:
                errors.append(f"BUNDLE_MANIFEST.json: missing file {rel}")
                continue
            if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
                errors.append(f"BUNDLE_MANIFEST.json: SHA256 mismatch for {rel}")
            if len(data) != entry.get("size_bytes"):
                errors.append(f"BUNDLE_MANIFEST.json: size mismatch for {rel}")
            stats["manifest_entries"] += 1
        missing = set(files) - {"BUNDLE_MANIFEST.json"} - recorded
        for rel in sorted(missing):
            errors.append(f"BUNDLE_MANIFEST.json: unlisted file {rel}")
    return errors, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="검사할 패키지 루트 (기본: 스크립트 상위)")
    parser.add_argument("--verify-manifest", action="store_true", help="현재 파일 전체의 manifest 해시·크기도 검사")
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        parser.error("root directory does not exist")
    errors, stats = check(root, args.verify_manifest)
    print(json.dumps({"status": "fail" if errors else "pass", "scope": "workspace static checks only; no CAD/API tests", "manifest_verified": args.verify_manifest, "counts": stats, "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
