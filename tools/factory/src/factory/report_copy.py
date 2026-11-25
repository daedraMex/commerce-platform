"""Copy a check's report folder out of an agent-written worktree, safely (#227).

The agent controls every byte of the worktree, so the copy never follows a link:
the walk opens each folder with ``O_NOFOLLOW`` relative to its parent's descriptor,
copies only regular files and folders, refuses a root that is a link, sets its own
modes (folders 0700, files 0600) and stops at a size and a file limit.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

MAX_REPORT_BYTES = 200 * 1024 * 1024
MAX_REPORT_FILES = 2000
MAX_DEPTH = 32
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
_CHUNK = 1024 * 1024


@dataclass
class CopyReport:
    files: int = 0
    bytes: int = 0
    skipped: int = 0
    stopped: list[str] = field(default_factory=list)

    def describe(self) -> str:
        text = f"copied {self.files} files ({self.bytes} bytes)"
        if self.skipped:
            text += f", skipped {self.skipped} links or special files"
        if self.stopped:
            text += f"; stopped: {self.stopped[0]}"
        return text


def copy_report(
    source: Path,
    target: Path,
    *,
    max_bytes: int = MAX_REPORT_BYTES,
    max_files: int = MAX_REPORT_FILES,
) -> CopyReport:
    """Copy ``source`` into ``target`` (created 0700); raise OSError when the root is a link."""
    report = CopyReport()
    root = os.open(source, _DIR_FLAGS)  # ELOOP when the root itself is a symlink
    try:
        target.mkdir(mode=0o700, parents=True)
        _copy_dir(root, target, report, max_bytes=max_bytes, max_files=max_files, depth=0)
    finally:
        os.close(root)
    return report


def _copy_dir(fd, target, report, *, max_bytes, max_files, depth):
    if depth > MAX_DEPTH:
        report.stopped.append(f"deeper than {MAX_DEPTH} folders")
        return
    for name in sorted(os.listdir(fd)):
        if report.stopped:
            return
        try:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(info.st_mode):
            try:
                child = os.open(name, _DIR_FLAGS, dir_fd=fd)
            except OSError:
                report.skipped += 1  # swapped for a link after the stat
                continue
            try:
                (target / name).mkdir(mode=0o700)
                _copy_dir(
                    child,
                    target / name,
                    report,
                    max_bytes=max_bytes,
                    max_files=max_files,
                    depth=depth + 1,
                )
            finally:
                os.close(child)
        elif stat.S_ISREG(info.st_mode):
            if report.files >= max_files:
                report.stopped.append(f"more than {max_files} files")
                return
            _copy_file(fd, name, target / name, report, max_bytes=max_bytes)
        else:
            report.skipped += 1


def _copy_file(fd, name, destination, report, *, max_bytes):
    try:
        source = os.open(name, _FILE_FLAGS, dir_fd=fd)
    except OSError:
        report.skipped += 1
        return
    try:
        if not stat.S_ISREG(os.fstat(source).st_mode):
            report.skipped += 1  # swapped for a FIFO or a device after the stat
            return
        out = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            while chunk := os.read(source, _CHUNK):
                if report.bytes + len(chunk) > max_bytes:
                    report.stopped.append(f"over {max_bytes} bytes")
                    break
                os.write(out, chunk)
                report.bytes += len(chunk)
        finally:
            os.close(out)
        report.files += 1
    finally:
        os.close(source)
