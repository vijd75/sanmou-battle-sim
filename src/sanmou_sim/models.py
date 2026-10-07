from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DamageKind(str, Enum):
    WEAPON = "weapon"
    STRATEGY = "strategy"
    DESERTER = "deserter"
    TRANSFER = "transfer"


class SkillTiming(str, Enum):
    PASSIVE = "passive"
    COMMAND = "command"
    ACTIVE = "active"
    PURSUIT = "pursuit"


@dataclass(slots=True)
class Modifier:
    name: str
    stat: str
    value: float
    expires_after_turn: int | None = None
    source_actor: str | None = None
    source_skill: str | None = None
    source_timing: SkillTiming | None = None
    end_of_round_decay: float = 0.0


@dataclass(slots=True)
class StatusEffect:
    name: str
    remaining_rounds: int | None = None
    stacks: int = 1
    max_stacks: int | None = None
    source_actor: str | None = None
    source_team: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class General:
    name: str
    troops: int
    force: int
    intellect: int
    command: int
    initiative: int
    skills: list[str]
    max_troops: int = 0
    team: str = ""
    position: str = "front"
    troop_type: str = ""
    faction: str = ""
    race: str = ""
    basic_target_weight: float = 1.0
    modifiers: list[Modifier] = field(default_factory=list)
    statuses: list[StatusEffect] = field(default_factory=list)
    preparations: dict[str, int] = field(default_factory=dict)
    wounded_troops: int = 0
    dead_troops: int = 0
    damage_bonus: float = 0.0
    damage_reduction: float = 0.0
    insight: float = 0.0
    critical_chance: float = 0.0
    evasion_chance: float = 0.0

    def __post_init__(self) -> None:
        if not self.max_troops:
            self.max_troops = self.troops

    @property
    def is_alive(self) -> bool:
        return self.troops > 0

    def stat(self, name: str) -> float:
        base = float(getattr(self, name))
        flat = sum(mod.value for mod in self.modifiers if mod.stat == name)
        percent = sum(mod.value for mod in self.modifiers if mod.stat == f"{name}_percent_bonus")
        return max(1.0, (base + flat) * max(0.05, 1.0 + percent))

    def modifier_total(self, name: str) -> float:
        return sum(mod.value for mod in self.modifiers if mod.stat == name)

    def healable_max_troops(self) -> int:
        return max(0, self.max_troops - self.dead_troops)

    def has_status(self, name: str) -> bool:
        return any(status.name == name and status.stacks > 0 for status in self.statuses)

    def status(self, name: str) -> StatusEffect | None:
        for status in self.statuses:
            if status.name == name and status.stacks > 0:
                return status
        return None

    def add_status(self, status: StatusEffect) -> None:
        source_skill = status.payload.get("source_skill")
        current = next(
            (
                existing for existing in self.statuses
                if existing.name == status.name
                and existing.source_actor == status.source_actor
                and existing.payload.get("source_skill") == source_skill
            ),
            None,
        )
        if current is None:
            self.statuses.append(status)
            return

        max_stacks = status.max_stacks or current.max_stacks
        current.max_stacks = max_stacks
        current.stacks += status.stacks
        if max_stacks is not None:
            current.stacks = min(current.stacks, max_stacks)
        if status.remaining_rounds is not None:
            if current.remaining_rounds is None:
                current.remaining_rounds = status.remaining_rounds
            else:
                current.remaining_rounds = max(current.remaining_rounds, status.remaining_rounds)
        current.payload.update(status.payload)
        current.source_actor = status.source_actor or current.source_actor
        current.source_team = status.source_team or current.source_team

    def consume_status_stack(self, name: str, stacks: int = 1) -> bool:
        current = self.status(name)
        if current is None:
            return False
        current.stacks -= stacks
        if current.stacks <= 0:
            self.statuses = [status for status in self.statuses if status is not current]
        return True

    def expire_modifiers(self, turn: int) -> None:
        self.modifiers = [
            mod for mod in self.modifiers if mod.expires_after_turn is None or mod.expires_after_turn > turn
        ]

    def tick_status_durations(self) -> None:
        for status in self.statuses:
            if status.remaining_rounds is not None:
                status.remaining_rounds -= 1

    def purge_expired_statuses(self) -> None:
        self.statuses = [
            status
            for status in self.statuses
            if status.remaining_rounds is None or status.remaining_rounds > 0
        ]

    def clear_preparations(self) -> None:
        self.preparations.clear()

    def remove_skill_effects_from(
        self,
        source_actor: str,
        source_skills: set[str],
    ) -> tuple[list[Modifier], list[StatusEffect]]:
        removed_modifiers = [
            modifier
            for modifier in self.modifiers
            if modifier.source_actor == source_actor and modifier.source_skill in source_skills
        ]
        removed_statuses = [
            status
            for status in self.statuses
            if status.source_actor == source_actor and status.payload.get("source_skill") in source_skills
        ]
        self.modifiers = [modifier for modifier in self.modifiers if modifier not in removed_modifiers]
        self.statuses = [status for status in self.statuses if status not in removed_statuses]
        return removed_modifiers, removed_statuses


@dataclass(slots=True)
class Team:
    name: str
    generals: list[General]
    formation_id: str = ""
    formation_name: str = ""

    def __post_init__(self) -> None:
        for general in self.generals:
            general.team = self.name

    @property
    def alive_generals(self) -> list[General]:
        return [general for general in self.generals if general.is_alive]

    @property
    def total_troops(self) -> int:
        return sum(general.troops for general in self.generals)

    @property
    def max_troops(self) -> int:
        return sum(general.max_troops for general in self.generals)

    @property
    def troop_loss(self) -> int:
        return max(0, self.max_troops - self.total_troops)

    @property
    def is_defeated(self) -> bool:
        return not self.alive_generals


@dataclass(slots=True)
class Battle:
    team_a: Team
    team_b: Team
    max_rounds: int = 8


@dataclass(slots=True)
class BattleResult:
    winner_name: str
    rounds: int
    teams: tuple[Team, Team]
    log: list[str]
    stats: list[SourceStat] = field(default_factory=list)
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    log_entries: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class SourceStat:
    team: str
    actor: str
    source: str
    activations: int = 0
    damage: int = 0
    healing: int = 0
