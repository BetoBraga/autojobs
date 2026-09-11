from pathlib import Path
import logging

from linkedin_easy_apply.logging_utils import CappedFileHandler


def test_capped_log_self_resets(tmp_path):
    path = tmp_path / "autojobs.log"
    handler = CappedFileHandler(path, max_bytes=1024)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("autojobs-test-capped")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    for i in range(20):
        logger.info("%03d %s", i, "x" * 180)
    handler.flush(); handler.close()
    assert path.exists()
    assert path.stat().st_size <= 1300
    text = path.read_text(encoding="utf-8")
    assert "xxxxxxxx" in text
