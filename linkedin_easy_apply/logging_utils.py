from __future__ import annotations

import logging
import os
from pathlib import Path

from .config import app_data_dir

MAX_LOG_BYTES = 100 * 1024 * 1024


def log_file_path() -> Path:
    path = app_data_dir() / "autojobs.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class CappedFileHandler(logging.FileHandler):
    """Single persistent log that self-resets at the configured size cap.

    The user specifically wants one useful debug file without unbounded disk use.
    When the next record would push the file beyond 100 MB, the existing file is
    deleted and a fresh log is started immediately.
    """

    def __init__(self, filename: str | os.PathLike[str] | None = None, *, max_bytes: int = MAX_LOG_BYTES):
        self.max_bytes = max(1024, int(max_bytes))
        super().__init__(str(filename or log_file_path()), mode="a", encoding="utf-8", delay=False)
        self._autojobs_persistent_handler = True

    def _reset_file(self) -> None:
        try:
            if self.stream:
                self.stream.flush()
                self.stream.close()
        except Exception:
            pass
        self.stream = None
        try:
            Path(self.baseFilename).unlink(missing_ok=True)
        except Exception:
            # If Windows temporarily holds the file handle, fall back to truncate.
            try:
                Path(self.baseFilename).write_text("", encoding="utf-8")
            except Exception:
                return
        try:
            self.stream = self._open()
            self.stream.write("autojobs log restarted after reaching the 100 MB safety limit.\n")
            self.stream.flush()
        except Exception:
            self.stream = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record) + self.terminator
            incoming = len(message.encode("utf-8", errors="replace"))
            try:
                current = Path(self.baseFilename).stat().st_size
            except Exception:
                current = 0
            if current + incoming >= self.max_bytes:
                self._reset_file()
            super().emit(record)
        except Exception:
            self.handleError(record)
