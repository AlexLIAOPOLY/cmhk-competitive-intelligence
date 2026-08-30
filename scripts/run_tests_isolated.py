#!/usr/bin/env python3
"""Run the unittest suite in a disposable copy-on-write workspace.

The application has legacy generators whose default output paths live below the
repository root.  This runner snapshots the current tracked tree plus visible
untracked source files, then runs tests only inside that snapshot.  On APFS and
filesystems supporting FICLONE the snapshot is copy-on-write; other filesystems
fall back to ordinary copies.
"""

from __future__ import annotations

import argparse
import ctypes
import fcntl
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


FICLONE = 0x40049409


def _git_root() -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(completed.stdout.strip()).resolve()


def _workspace_paths(root: Path) -> list[Path]:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        check=True,
        capture_output=True,
    )
    paths = {
        Path(os.fsdecode(raw))
        for raw in completed.stdout.split(b"\0")
        if raw
    }
    return sorted(paths, key=lambda path: os.fsencode(path.as_posix()))


def _snapshot_index(root: Path, destination: Path) -> dict[str, int]:
    """Materialize exactly the staged Git index, excluding unrelated worktree edits."""
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "checkout-index",
            "--all",
            "--force",
            f"--prefix={destination}{os.sep}",
        ],
        check=True,
    )
    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    count = sum(1 for raw in completed.stdout.split(b"\0") if raw)
    return {"index": count, "reflink": 0, "copy": 0, "symlink": 0, "missing": 0}


def _clonefile_macos(source: Path, destination: Path) -> bool:
    if sys.platform != "darwin":
        return False
    libc = ctypes.CDLL(None, use_errno=True)
    clonefile = getattr(libc, "clonefile", None)
    if clonefile is None:
        return False
    clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
    clonefile.restype = ctypes.c_int
    result = clonefile(os.fsencode(source), os.fsencode(destination), 0)
    return result == 0


def _reflink_linux(source: Path, destination: Path) -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        with source.open("rb") as source_handle, destination.open("xb") as destination_handle:
            fcntl.ioctl(destination_handle.fileno(), FICLONE, source_handle.fileno())
        return True
    except OSError:
        destination.unlink(missing_ok=True)
        return False


def _copy_file(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        destination.symlink_to(os.readlink(source))
        return "symlink"
    if _clonefile_macos(source, destination):
        shutil.copystat(source, destination, follow_symlinks=False)
        return "reflink"
    destination.unlink(missing_ok=True)
    if _reflink_linux(source, destination):
        shutil.copystat(source, destination, follow_symlinks=False)
        return "reflink"
    shutil.copy2(source, destination)
    return "copy"


def _snapshot(root: Path, destination: Path) -> dict[str, int]:
    counts = {"reflink": 0, "copy": 0, "symlink": 0, "missing": 0}
    for relative in _workspace_paths(root):
        source = root / relative
        if not source.exists() and not source.is_symlink():
            counts["missing"] += 1
            continue
        if source.is_dir() and not source.is_symlink():
            continue
        method = _copy_file(source, destination / relative)
        counts[method] += 1
    return counts


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run unittest discovery without allowing tests to write into the working tree."
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the isolated workspace after the run for failure investigation.",
    )
    parser.add_argument(
        "--index",
        action="store_true",
        help="Test exactly the staged Git index, excluding unstaged and untracked files.",
    )
    parser.add_argument(
        "unittest_args",
        nargs=argparse.REMAINDER,
        help="Arguments passed to python -m unittest; prefix them with --.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    root = _git_root()
    isolated_root = Path(tempfile.mkdtemp(prefix="cmhk-tests-")) / "workspace"
    isolated_root.mkdir()
    counts = _snapshot_index(root, isolated_root) if args.index else _snapshot(root, isolated_root)
    copied = counts["reflink"] + counts["copy"] + counts["symlink"]
    if args.index:
        print(f"Isolated staged-index workspace ready: {counts['index']} files")
    else:
        print(
            "Isolated test workspace ready: "
            f"{copied} files ({counts['reflink']} copy-on-write, {counts['copy']} copied)"
        )

    unittest_args = list(args.unittest_args)
    if unittest_args[:1] == ["--"]:
        unittest_args = unittest_args[1:]
    if not unittest_args:
        unittest_args = ["discover", "-s", "tests", "-t", "."]

    environment = os.environ.copy()
    environment.update(
        {
            "CMHK_TEST_ISOLATED": "1",
            "CMHK_INTERNAL_AI_API_KEY": "cmhk-test-placeholder",
            "CMHK_RUNTIME_ROOT": str(isolated_root),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(isolated_root),
        }
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", *unittest_args],
            cwd=isolated_root,
            env=environment,
        )
        return completed.returncode
    finally:
        if args.keep:
            print(f"Isolated workspace kept at: {isolated_root}")
        else:
            shutil.rmtree(isolated_root.parent)


if __name__ == "__main__":
    raise SystemExit(main())
