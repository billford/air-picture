"""Keeping air_picture.log from growing without bound.

Ported from the pool project, which hit the same trap. Rotating this log is not
the usual problem, because of who owns the file descriptor.

**launchd opens `StandardOutPath` / `StandardErrorPath` itself and holds the fd
for the life of the process.** Every plist here - scan-30min, scan-morning,
scan-evening, report-daily, build-site-hourly - points both streams at
air_picture.log, and the scanner's output reaches it that way rather than
through Python's logging module. Rename or unlink that file and launchd carries
on writing to the now-unlinked inode: the visible log sits empty, the disk fills
anyway, and nothing indicates why. Classic logrotate-without-copytruncate.

So a `RotatingFileHandler` is the wrong tool here - it renames. The file is
truncated **in place** instead, preserving the inode, so launchd's O_APPEND
descriptor keeps working against the shortened file.
"""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG_FILE = HERE / "air_picture.log"

# The scanner runs 48+ times a day and its output is genuinely useful while
# debugging a scan, so this keeps more than the pool project does. Everything of
# lasting value is in the database; this is a tail for the recent past.
MAX_BYTES = 4 * 1024 * 1024
KEEP_FRACTION = 0.5


def trim_in_place(path: Path = None, max_bytes: int = MAX_BYTES,
                  keep_fraction: float = KEEP_FRACTION) -> bool:
    """Shortens a file another process is appending to, keeping the tail.

    Truncating rather than renaming is the whole point: launchd's descriptor
    stays valid and its O_APPEND writes resume against the shortened file. A
    rename would leave it writing to an inode with no name.

    Returns True if it trimmed.
    """
    path = Path(path or LOG_FILE)
    try:
        if not path.exists() or path.stat().st_size <= max_bytes:
            return False
        keep = int(max_bytes * keep_fraction)
        with path.open("rb") as f:
            f.seek(-keep, os.SEEK_END)
            tail = f.read()
        # Drop a partial first line so the file doesn't start mid-sentence.
        newline = tail.find(b"\n")
        if newline != -1:
            tail = tail[newline + 1:]
        with path.open("r+b") as f:
            f.truncate(0)
            f.write(b"[earlier entries trimmed]\n")
            f.write(tail)
        return True
    except OSError:
        # Log housekeeping must never be the thing that breaks a scan.
        return False
