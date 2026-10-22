from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum, Enum
from typing import Any


class Severity(IntEnum):
    CRITICAL = 5
    HIGH = 4
    MEDIUM = 3
    LOW = 2
    INFO = 1

    @property
    def label(self) -> str:
        return self.name


class Layer(Enum):
    L1_RAW = "raw heuristics"
    L2_RECONCILE = "raw->cold reconciliation"
    L3_COLD = "cold_case integrity"


@dataclass
class Finding:
    count: int
    case_ids: list[int]
    detail: str
    verify_items: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_findings(self) -> bool:
        return self.count > 0


@dataclass
class AuditContext:
    source: str          # adapter name, e.g. "cold_case_fl_fdle"
    source_code: str     # etl.source_system.source_code, e.g. "FDLE_FL"
    state: str           # "FL"
    dataset_version_id: int
    raw_table: str       # fully-qualified, e.g. "raw_cold_case.cold_case_fl_fdle_dv1199"
    total_cases: int


@dataclass
class Rule:
    id: str
    title: str
    severity: Severity
    layer: Layer
    verify_in_browser: bool
    run: Callable[[Any, AuditContext], Finding]


@dataclass
class SourceAuditConfig:
    source: str          # adapter name / raw-table prefix
    source_code: str     # etl source_code
    state: str
    rules: list[Rule]
