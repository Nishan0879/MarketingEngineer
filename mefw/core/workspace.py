"""A client workspace: one directory per client, laid out as in Section 17.2.

Everything an agent touches for a client is resolved through its Workspace, so
one client's data never reaches another's (Section 11.4, rule 9).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .errors import OutsideWorkspace

CONFIG_PATH = "profile/mefw.toml"

# Universal funnel (Section 7). A profile maps its own stage names onto these.
FUNNEL = ["attract", "inquire", "qualify", "meet", "commit", "retain"]


@dataclass
class AgentConfig:
    name: str
    engine: str
    level: int
    spec: str
    max_actions_per_day: int
    max_consecutive_errors: int = 2


@dataclass
class Segment:
    """A group of buyers with its own funnel, e.g. members vs. office tenants (Section 7).

    Leads are assigned by matching the lead's segment value from the lead-tracking
    tool against `match`. Stage names and audit thresholds can differ per segment.
    """

    name: str
    label: str
    match: set[str]
    cycle_days: int
    stage_map: dict[str, str] = field(default_factory=dict)
    cold_audit: dict = field(default_factory=dict)


ALL = "all"
UNASSIGNED = "unassigned"


@dataclass
class Config:
    client_id: str
    timezone: str
    stage_map: dict[str, str]
    cycle_days: int
    agents: dict[str, AgentConfig]
    conversion: dict = field(default_factory=dict)
    csv: dict = field(default_factory=dict)
    segments: dict[str, Segment] = field(default_factory=dict)
    customer_truth: dict = field(default_factory=dict)
    signals_csv: dict = field(default_factory=dict)
    north_star: dict = field(default_factory=dict)


class Workspace:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        cfg_file = self.root / CONFIG_PATH
        if not cfg_file.exists():
            raise FileNotFoundError(
                f"No {CONFIG_PATH} in {self.root}. Run `mefw init` first."
            )
        self.config = load_config(cfg_file)

    @property
    def client_id(self) -> str:
        return self.config.client_id

    def path(self, rel: str) -> Path:
        """Resolve a path inside the workspace, refusing anything outside it."""
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            raise OutsideWorkspace(f"{rel} resolves outside {self.root}")
        return p

    @property
    def db_path(self) -> Path:
        return self.path("data/ledger.db")

    @property
    def log_path(self) -> Path:
        return self.path("logs/agent-activity.jsonl")

    @property
    def control_path(self) -> Path:
        return self.path("control/pause.json")

    def segment_for(self, raw: str | None) -> str:
        """Which configured segment a lead belongs to, from its segment value."""
        if not self.config.segments:
            return ALL
        key = (raw or "").strip().lower()
        for seg in self.config.segments.values():
            if key in seg.match:
                return seg.name
        return UNASSIGNED

    def segment_names(self) -> list[str]:
        return list(self.config.segments) or [ALL]

    def cycle_days(self, segment: str) -> int:
        seg = self.config.segments.get(segment)
        return seg.cycle_days if seg else self.config.cycle_days

    def segment_label(self, segment: str) -> str:
        seg = self.config.segments.get(segment)
        if seg:
            return seg.label
        return {ALL: "All leads", UNASSIGNED: "No matching segment"}.get(segment, segment)

    def canonical_stage(self, client_stage: str | None, segment_raw: str | None = None) -> str | None:
        """Map a client's stage name to the universal funnel stage, using the
        lead's segment's own stage names first."""
        if not client_stage:
            return None
        key = client_stage.strip().lower()
        seg = self.config.segments.get(self.segment_for(segment_raw))
        if seg and key in seg.stage_map:
            return seg.stage_map[key]
        if key in self.config.stage_map:
            return self.config.stage_map[key]
        if key in FUNNEL:
            return key
        return None


def load_config(path: Path) -> Config:
    raw = tomllib.loads(path.read_text())
    client = raw.get("client", {})
    funnel = raw.get("funnel", {})
    stage_map = _stage_map(funnel.get("stages", {}), path)
    cycle_days = int(funnel.get("cycle_days", 30))
    segments = {}
    for name, sc in raw.get("segments", {}).items():
        if name in (ALL, UNASSIGNED):
            raise ValueError(f"'{name}' is reserved and can't be a segment name in {path}")
        segments[name] = Segment(
            name=name,
            label=sc.get("label", name.replace("-", " ").title()),
            match={m.strip().lower() for m in sc.get("match", [])},
            cycle_days=int(sc.get("cycle_days", cycle_days)),
            stage_map=_stage_map(sc.get("stages", {}), path),
            cold_audit=sc.get("cold_audit", {}),
        )
    agents = {}
    for name, a in raw.get("agents", {}).items():
        agents[name] = AgentConfig(
            name=name,
            engine=a["engine"],
            level=int(a.get("level", 0)),
            spec=a["spec"],
            max_actions_per_day=int(a.get("max_actions_per_day", 10)),
            max_consecutive_errors=int(a.get("max_consecutive_errors", 2)),
        )
    return Config(
        client_id=client["id"],
        timezone=client.get("timezone", "UTC"),
        stage_map=stage_map,
        cycle_days=cycle_days,
        agents=agents,
        conversion=raw.get("conversion", {}),
        csv=raw.get("adapters", {}).get("csv", {}),
        segments=segments,
        customer_truth=raw.get("customer_truth", {}),
        signals_csv=raw.get("adapters", {}).get("signals_csv", {}),
        north_star=raw.get("north_star", {}),
    )


def _stage_map(stages: dict, path: Path) -> dict[str, str]:
    out = {}
    for canonical, names in stages.items():
        if canonical not in FUNNEL:
            raise ValueError(f"Unknown funnel stage '{canonical}' in {path}")
        for n in names if isinstance(names, list) else [names]:
            out[n.strip().lower()] = canonical
    return out
