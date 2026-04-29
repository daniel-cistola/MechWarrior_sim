"""
SimUnit — represents one BattleMech during a simulation run.

Separates static stats (loaded from CSV, never mutated) from
runtime state (health, damage dealt, etc.) which resets each run.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional

from sim.constants import ROLE_PREFERRED_RANGE, DEFAULT_PREFERRED_RANGE


def _parse_move(bf_move_str: str) -> int:
    """
    Extract primary move value from bf_move string.

    The MUL encodes move as strings like: '8"', '6j"', '4/6j"', '10"'
    We take the first integer found — this is the ground move (or jump
    if ground-only is absent). Jump move is used for TMM purposes already
    captured in bf_tmm, so primary move governs range contest speed.
    """
    if not bf_move_str:
        return 4
    match = re.search(r"(\d+)", str(bf_move_str))
    return int(match.group(1)) if match else 4


@dataclass
class SimUnit:
    # ── Identity ──────────────────────────────────────────────────────────────
    mul_id:   int
    name:     str
    variant:  str
    role:     str

    # ── Static stats (never change during a run) ──────────────────────────────
    tonnage:           float
    bf_size:           int
    bf_tmm:            int       # target movement modifier (harder to hit)
    bf_armor:          int
    bf_structure:      int
    bf_damage_short:   int
    bf_damage_medium:  int
    bf_damage_long:    int
    bf_overheat:       int
    bf_point_value:    int
    move:              int       # parsed from bf_move string

    # ── Derived / cached ──────────────────────────────────────────────────────
    max_health:        int = field(init=False)
    preferred_range:   int = field(init=False)

    # ── Runtime state (reset each simulation run) ─────────────────────────────
    health:            int       = field(init=False)
    damage_dealt:      int       = field(init=False)
    damage_taken:      int       = field(init=False)
    kills:             int       = field(init=False)
    turns_active:      int       = field(init=False)
    alive:             bool      = field(init=False)

    def __post_init__(self):
        self.max_health      = self.bf_armor + self.bf_structure
        self.preferred_range = ROLE_PREFERRED_RANGE.get(
            self.role, DEFAULT_PREFERRED_RANGE
        )
        self.reset()

    def reset(self):
        """Restore to full health. Call before every simulation run."""
        self.health       = self.max_health
        self.damage_dealt = 0
        self.damage_taken = 0
        self.kills        = 0
        self.turns_active = 0
        self.alive        = True

    def apply_damage(self, amount: int):
        """Reduce health by amount. Mark as destroyed if health hits 0."""
        actual = min(amount, self.health)   # can't overkill beyond 0
        self.health       -= actual
        self.damage_taken += actual
        if self.health <= 0:
            self.alive = False

    def damage_at_range(self, range_band: int) -> int:
        """Return damage value for the given range band."""
        if range_band == 0: return self.bf_damage_short
        if range_band == 1: return self.bf_damage_medium
        return self.bf_damage_long

    @classmethod
    def from_row(cls, row) -> "SimUnit":
        """
        Build a SimUnit from a pandas Series or dict row
        loaded from battlemechs_sim_ready.csv.
        """
        return cls(
            mul_id           = int(row["mul_id"]),
            name             = str(row["name"]),
            variant          = str(row.get("variant", "")),
            role             = str(row.get("role", "Striker")),
            tonnage          = float(row["tonnage"]),
            bf_size          = int(row.get("bf_size", 2)),
            bf_tmm           = int(row.get("bf_tmm", 0)),
            bf_armor         = int(row.get("bf_armor", 1)),
            bf_structure     = int(row.get("bf_structure", 1)),
            bf_damage_short  = int(row.get("bf_damage_short", 0)),
            bf_damage_medium = int(row.get("bf_damage_medium", 0)),
            bf_damage_long   = int(row.get("bf_damage_long", 0)),
            bf_overheat      = int(row.get("bf_overheat", 0)),
            bf_point_value   = int(row.get("bf_point_value", 0)),
            move             = _parse_move(row.get("bf_move", "4")),
        )

    def __repr__(self):
        status = f"{self.health}/{self.max_health}hp" if self.alive else "DESTROYED"
        return f"<{self.name} {self.variant} [{self.role}] {status}>"
