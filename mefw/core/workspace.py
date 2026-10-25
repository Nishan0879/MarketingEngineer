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
class Config:
    client_id: str
    timezone: str
    stage_map: dict[str, str]
    cycle_days: int
    agents: dict[str, AgentConfig]
    conversion: dict = field(default_factory=dict)
    csv: dict = field(default_factory=dict)


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

    def canonical_stage(self, client_stage: str | None) -> str | None:
        """Map a client's stage name to the universal funnel stage."""
        if not client_stage:
            return None
        key = client_stage.strip().lower()
        if key in self.config.stage_map:
            return self.config.stage_map[key]
        if key in FUNNEL:
            return key
        return None


def load_config(path: Path) -> Config:
    raw = tomllib.loads(path.read_text())
    client = raw.get("client", {})
    funnel = raw.get("funnel", {})
    stage_map = {}
    for canonical, names in funnel.get("stages", {}).items():
        if canonical not in FUNNEL:
            raise ValueError(f"Unknown funnel stage '{canonical}' in {path}")
        for n in names if isinstance(names, list) else [names]:
            stage_map[n.strip().lower()] = canonical
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
        cycle_days=int(funnel.get("cycle_days", 30)),
        agents=agents,
        conversion=raw.get("conversion", {}),
        csv=raw.get("adapters", {}).get("csv", {}),
    )
