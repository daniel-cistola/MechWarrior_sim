"""
Monte Carlo runner — runs N simulations of Force A vs Force B
and returns structured results aligned to the SIM_RUN / UNIT_RESULT schema.
"""

from __future__ import annotations
import random
import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Any

from sim.unit import SimUnit
from sim.combat import resolve_turn
from sim.constants import (
    DEFAULT_SIMULATIONS, MAX_TURNS, STARTING_RANGE, RANGE_NAMES
)


# ── Result structures (mirror the DB schema) ─────────────────────────────────

@dataclass
class UnitResult:
    run_id:           str
    mul_id:           int
    name:             str
    variant:          str
    side:             str        # "A" or "B"
    survived:         bool
    health_remaining: int
    health_max:       int
    damage_dealt:     int
    damage_taken:     int
    kills:            int
    turns_active:     int
    point_value:      int

    def efficiency(self) -> float:
        """Damage dealt per point value — core balance metric."""
        if self.point_value == 0:
            return 0.0
        return self.damage_dealt / self.point_value


@dataclass
class SimRun:
    run_id:           str
    force_a_name:     str
    force_b_name:     str
    winner:           str        # "A", "B", or "Draw"
    turns_elapsed:    int
    seed:             int
    final_range:      str        # range band name at end of combat
    unit_results:     List[UnitResult] = field(default_factory=list)


# ── Core simulation loop ──────────────────────────────────────────────────────

def _run_single(
    force_a: List[SimUnit],
    force_b: List[SimUnit],
    force_a_name: str,
    force_b_name: str,
    seed: int,
) -> SimRun:
    """Run one complete engagement to completion."""
    rng = random.Random(seed)

    # Reset all units to full health
    for u in force_a + force_b:
        u.reset()

    current_range = STARTING_RANGE
    turns_elapsed = 0
    winner        = "Draw"

    for turn in range(1, MAX_TURNS + 1):
        current_range, _ = resolve_turn(
            turn_number   = turn,
            side_a        = force_a,
            side_b        = force_b,
            current_range = current_range,
            rng           = rng,
        )
        turns_elapsed = turn

        a_alive = any(u.alive for u in force_a)
        b_alive = any(u.alive for u in force_b)

        if not a_alive and not b_alive:
            winner = "Draw"
            break
        elif not b_alive:
            winner = "A"
            break
        elif not a_alive:
            winner = "B"
            break

    run_id = str(uuid.uuid4())

    unit_results = []
    for side, units in (("A", force_a), ("B", force_b)):
        for u in units:
            unit_results.append(UnitResult(
                run_id           = run_id,
                mul_id           = u.mul_id,
                name             = u.name,
                variant          = u.variant,
                side             = side,
                survived         = u.alive,
                health_remaining = u.health,
                health_max       = u.max_health,
                damage_dealt     = u.damage_dealt,
                damage_taken     = u.damage_taken,
                kills            = u.kills,
                turns_active     = u.turns_active,
                point_value      = u.bf_point_value,
            ))

    return SimRun(
        run_id        = run_id,
        force_a_name  = force_a_name,
        force_b_name  = force_b_name,
        winner        = winner,
        turns_elapsed = turns_elapsed,
        seed          = seed,
        final_range   = RANGE_NAMES[current_range],
        unit_results  = unit_results,
    )


# ── Monte Carlo runner ────────────────────────────────────────────────────────

@dataclass
class MatchupResults:
    force_a_name:  str
    force_b_name:  str
    n_simulations: int
    runs:          List[SimRun] = field(default_factory=list)

    # ── Aggregate stats ───────────────────────────────────────────────────────

    def win_rate_a(self) -> float:
        wins = sum(1 for r in self.runs if r.winner == "A")
        return wins / self.n_simulations

    def win_rate_b(self) -> float:
        wins = sum(1 for r in self.runs if r.winner == "B")
        return wins / self.n_simulations

    def draw_rate(self) -> float:
        draws = sum(1 for r in self.runs if r.winner == "Draw")
        return draws / self.n_simulations

    def avg_turns(self) -> float:
        return sum(r.turns_elapsed for r in self.runs) / self.n_simulations

    def unit_stats(self) -> Dict[int, Dict[str, Any]]:
        """
        Aggregate per-unit stats across all runs.
        Returns dict keyed by mul_id with survival rate, avg damage, efficiency.
        """
        from collections import defaultdict
        agg: Dict[int, Dict] = defaultdict(lambda: {
            "name": "", "variant": "", "side": "",
            "point_value": 0, "role": "",
            "survived": 0, "damage_dealt": 0,
            "damage_taken": 0, "turns_active": 0,
            "count": 0,
        })

        for run in self.runs:
            for ur in run.unit_results:
                a = agg[ur.mul_id]
                a["name"]         = ur.name
                a["variant"]      = ur.variant
                a["side"]         = ur.side
                a["point_value"]  = ur.point_value
                a["survived"]    += int(ur.survived)
                a["damage_dealt"] += ur.damage_dealt
                a["damage_taken"] += ur.damage_taken
                a["turns_active"] += ur.turns_active
                a["count"]        += 1

        # Normalise to per-run averages
        results = {}
        for mid, a in agg.items():
            n = a["count"]
            results[mid] = {
                "name":           a["name"],
                "variant":        a["variant"],
                "side":           a["side"],
                "point_value":    a["point_value"],
                "survival_rate":  a["survived"] / n,
                "avg_damage_dealt":  a["damage_dealt"] / n,
                "avg_damage_taken":  a["damage_taken"] / n,
                "avg_turns_active":  a["turns_active"] / n,
                "efficiency":     (a["damage_dealt"] / n) / max(a["point_value"], 1),
            }
        return results

    def summary(self) -> str:
        """Human-readable summary of the matchup."""
        us = self.unit_stats()
        lines = [
            f"{'─' * 55}",
            f"  {self.force_a_name}  vs  {self.force_b_name}",
            f"  {self.n_simulations} simulations",
            f"{'─' * 55}",
            f"  Side A win rate : {self.win_rate_a():.1%}",
            f"  Side B win rate : {self.win_rate_b():.1%}",
            f"  Draw rate       : {self.draw_rate():.1%}",
            f"  Avg turns       : {self.avg_turns():.1f}",
            f"{'─' * 55}",
            f"  Unit performance (avg per run):",
        ]
        for mid, s in sorted(us.items(), key=lambda x: x[1]["side"]):
            lines.append(
                f"  [{s['side']}] {s['name']} {s['variant']:<12} "
                f"surv={s['survival_rate']:.0%}  "
                f"dmg={s['avg_damage_dealt']:.1f}  "
                f"eff={s['efficiency']:.2f}"
            )
        lines.append(f"{'─' * 55}")
        return "\n".join(lines)


def run_matchup(
    force_a:       List[SimUnit],
    force_b:       List[SimUnit],
    force_a_name:  str = "Force A",
    force_b_name:  str = "Force B",
    n_simulations: int = DEFAULT_SIMULATIONS,
    base_seed:     int = 42,
    verbose:       bool = False,
) -> MatchupResults:
    """
    Run N simulations of Force A vs Force B.

    Each run gets a deterministic but unique seed (base_seed + run_index)
    so results are fully reproducible.

    Args:
        force_a / force_b : lists of SimUnit (will be reset each run)
        n_simulations     : number of Monte Carlo passes
        base_seed         : seed for run 0; subsequent runs use base_seed + i
        verbose           : print progress every 100 runs

    Returns:
        MatchupResults with all run data and aggregate helpers
    """
    results = MatchupResults(
        force_a_name  = force_a_name,
        force_b_name  = force_b_name,
        n_simulations = n_simulations,
    )

    for i in range(n_simulations):
        if verbose and i % 100 == 0:
            print(f"  Run {i}/{n_simulations}...")

        run = _run_single(
            force_a      = force_a,
            force_b      = force_b,
            force_a_name = force_a_name,
            force_b_name = force_b_name,
            seed         = base_seed + i,
        )
        results.runs.append(run)

    return results
