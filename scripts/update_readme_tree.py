#!/usr/bin/env python3
"""Regenerate the ASCII tree inside the `## Project Structure` section of README.md.

Usage:
    python scripts/update_readme_tree.py                 # project root is auto-detected
    python scripts/update_readme_tree.py path/to/project # or pass it explicitly
    python scripts/update_readme_tree.py --check         # exit 1 if README is stale (no write)

Designed to be run by a Claude Code hook (non-interactive, silent when nothing
changed, idempotent) and manually by a human.
"""
import argparse
import fnmatch
import os
import re
import sys
from pathlib import Path

# Hardcoded global fallbacks in case no .gitignore is present
GLOBAL_IGNORED_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".pytest_cache",
    ".idea",
    ".vscode",
    "*.user",
    "bin",
    "obj",
}

SECTION_HEADING = re.compile(r"^##\s+Project Structure\s*$")
ANY_H2 = re.compile(r"^##\s+(?!#)")  # level-2 heading only (not ###)
FENCE = re.compile(r"^\s*```")


# --------------------------------------------------------------------------
# Tree building (unchanged logic from the original script)
# --------------------------------------------------------------------------
def parse_gitignore(gitignore_path: Path) -> list:
    patterns = []
    if not gitignore_path.exists():
        return patterns
    try:
        with open(gitignore_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.endswith("/"):
                    line = line[:-1]
                patterns.append(line)
    except Exception as e:
        print(f"Warning: could not read .gitignore: {e}", file=sys.stderr)
    return patterns


def should_ignore(item: Path, base_path: Path, gitignore_patterns: list) -> bool:
    if item.name == ".git":
        return True

    if not gitignore_patterns and item.name in GLOBAL_IGNORED_DIRS:
        return True

    relative_path_str = str(item.relative_to(base_path)).replace(os.sep, "/")
    item_name = item.name

    for pattern in gitignore_patterns:
        if pattern == item_name or pattern == relative_path_str:
            return True
        if fnmatch.fnmatch(item_name, pattern) or fnmatch.fnmatch(
            relative_path_str, pattern
        ):
            return True
        if "/" not in pattern and any(
            fnmatch.fnmatch(part, pattern) for part in Path(relative_path_str).parts
        ):
            return True
        if pattern.endswith("/*") and not pattern.endswith("/**/*"):
            folder_pattern = pattern[:-2]
            folder_pattern_name = folder_pattern.rsplit("/", 1)[-1]
            if item.is_dir() and (
                fnmatch.fnmatch(item_name, folder_pattern_name)
                or fnmatch.fnmatch(relative_path_str, folder_pattern)
            ):
                return True

    return False


def generate_tree(
    dir_path: Path, base_path: Path, gitignore_patterns: list, prefix: str = ""
) -> list:
    tree_lines = []
    try:
        items = [
            item
            for item in dir_path.iterdir()
            if not should_ignore(item, base_path, gitignore_patterns)
        ]
        items.sort(key=lambda x: (not x.is_dir(), x.name.lower()))
    except PermissionError:
        return [f"{prefix}└── [Permission Denied]"]

    count = len(items)
    for i, item in enumerate(items):
        is_last = i == count - 1
        connector = "└── " if is_last else "├── "
        tree_lines.append(f"{prefix}{connector}{item.name}")
        if item.is_dir():
            next_prefix = prefix + ("    " if is_last else "│   ")
            tree_lines.extend(
                generate_tree(item, base_path, gitignore_patterns, next_prefix)
            )
    return tree_lines


def build_tree_text(target: Path) -> list:
    patterns = parse_gitignore(target / ".gitignore")
    root_name = target.name or "root"
    return [f"{root_name}/"] + generate_tree(target, target, patterns)


# --------------------------------------------------------------------------
# README patching
# --------------------------------------------------------------------------
def patch_readme(content: str, tree_lines: list) -> str:
    """Replace the first fenced block under '## Project Structure'.

    Everything else in the README (including '### Folder guide' and any text
    after the code fence) is left untouched.
    """
    newline = "\r\n" if "\r\n" in content else "\n"
    lines = content.splitlines()

    start = next((i for i, l in enumerate(lines) if SECTION_HEADING.match(l)), None)
    if start is None:
        raise ValueError("No '## Project Structure' heading found in README.")

    # Section ends at the next level-2 heading (### subsections stay inside it)
    end = next(
        (i for i in range(start + 1, len(lines)) if ANY_H2.match(lines[i])),
        len(lines),
    )

    open_idx = next((i for i in range(start + 1, end) if FENCE.match(lines[i])), None)
    new_block = ["```text", *tree_lines, "```"]

    if open_idx is None:
        # Section exists but has no code block yet: insert one after the heading
        lines[start + 1 : start + 1] = ["", *new_block]
    else:
        close_idx = next(
            (i for i in range(open_idx + 1, end) if FENCE.match(lines[i])), None
        )
        if close_idx is None:
            raise ValueError("Unterminated code fence in Project Structure section.")
        lines[open_idx : close_idx + 1] = new_block

    trailing = newline if content.endswith(("\n", "\r\n")) else ""
    return newline.join(lines) + trailing


ROOT_MARKERS = (".git", "global.json", "package.json", "pyproject.toml")
ROOT_MARKER_GLOBS = ("*.sln", "*.slnx")


def _has_marker(d: Path) -> bool:
    return any((d / m).exists() for m in ROOT_MARKERS) or any(
        next(d.glob(g), None) for g in ROOT_MARKER_GLOBS
    )


def _readme_has_section(d: Path, readme_name: str) -> bool:
    readme = d / readme_name
    try:
        text = readme.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return any(SECTION_HEADING.match(l) for l in text.splitlines())


def detect_project_root(readme_name: str) -> Path:
    """Find the project root without asking the user.

    Order:
      1. $CLAUDE_PROJECT_DIR (set by Claude Code when it runs hooks)
      2. Nearest parent of this script / the cwd whose README has a
         '## Project Structure' section
      3. Nearest parent of this script / the cwd with a repo/solution marker
         (.git, *.sln, *.slnx, global.json, package.json, pyproject.toml)
      4. The current directory
    """
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and Path(env).is_dir():
        return Path(env).resolve()

    starts = [Path(__file__).resolve().parent, Path.cwd().resolve()]
    for check in (lambda d: _readme_has_section(d, readme_name), _has_marker):
        for start in starts:
            for d in (start, *start.parents):
                if check(d):
                    return d
    return Path.cwd().resolve()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path", nargs="?", default=None, help="Project root (default: auto-detected)")
    ap.add_argument("--readme", default="README.md", help="README path relative to project root")
    ap.add_argument("--check", action="store_true", help="Don't write; exit 1 if README is out of date")
    args = ap.parse_args()

    root = (
        Path(args.path).expanduser().resolve()
        if args.path
        else detect_project_root(args.readme)
    )
    if not root.is_dir():
        print(f"Error: '{root}' is not a directory.", file=sys.stderr)
        return 1

    readme = root / args.readme
    if not readme.is_file():
        print(f"Error: {readme} not found.", file=sys.stderr)
        return 1

    # newline="" preserves the file's existing line endings on read
    with open(readme, "r", encoding="utf-8", newline="") as f:
        original = f.read()

    try:
        updated = patch_readme(original, build_tree_text(root))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if updated == original:
        return 0  # already up to date: stay silent

    if args.check:
        print("README Project Structure is out of date.", file=sys.stderr)
        return 1

    with open(readme, "w", encoding="utf-8", newline="") as f:
        f.write(updated)
    print(f"Updated Project Structure in {readme.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())