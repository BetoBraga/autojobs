from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class JobInfo:
    job_id: str
    title: str = ""
    company: str = ""
    location: str = ""
    location_source: str = ""
    location_confidence: str = ""
    url: str = ""


@dataclass
class RunStats:
    discovered: int = 0
    processed: int = 0
    filtered: int = 0
    attempted: int = 0
    applied: int = 0
    skipped: int = 0
    failed: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)
