"""
Monte Carlo runner — runs N simulations of Force A vs Force B
and returns structured results aligned to the SIM_RUN / UNIT_RESULT schema.
"""

from __future__ import annotations
import random
import uuid
import os
import csv as csv_module
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional

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
    base_seed:     int                # combat RNG seed this batch started from
    batch_id:      str                # short unique ID for this matchup run
    force_a_seed:  Optional[int]      # seed used to build force A (None if manual)
    force_b_seed:  Optional[int]      # seed used to build force B (None if manual)
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
            "point_value": 0,
            "survived": 0, "damage_dealt": 0,
            "damage_taken": 0, "turns_active": 0,
            "count": 0,
        })

        for run in self.runs:
            for ur in run.unit_results:
                a = agg[ur.mul_id]
                a["name"]          = ur.name
                a["variant"]       = ur.variant
                a["side"]          = ur.side
                a["point_value"]   = ur.point_value
                a["survived"]     += int(ur.survived)
                a["damage_dealt"]  += ur.damage_dealt
                a["damage_taken"]  += ur.damage_taken
                a["turns_active"]  += ur.turns_active
                a["count"]         += 1

        results = {}
        for mid, a in agg.items():
            n = a["count"]
            results[mid] = {
                "name":              a["name"],
                "variant":           a["variant"],
                "side":              a["side"],
                "point_value":       a["point_value"],
                "survival_rate":     a["survived"] / n,
                "avg_damage_dealt":  a["damage_dealt"] / n,
                "avg_damage_taken":  a["damage_taken"] / n,
                "avg_turns_active":  a["turns_active"] / n,
                "efficiency":        (a["damage_dealt"] / n) / max(a["point_value"], 1),
            }
        return results

    def summary(self) -> str:
        """Human-readable summary of the matchup."""
        us = self.unit_stats()

        def _seed_str(s): return str(s) if s is not None else "manual"

        lines = [
            f"{'─' * 60}",
            f"  {self.force_a_name}  vs  {self.force_b_name}",
            f"  {self.n_simulations} simulations  |  batch: {self.batch_id}",
            f"  combat seed : {self.base_seed}",
            f"  force seeds : A={_seed_str(self.force_a_seed)}"
            f"  B={_seed_str(self.force_b_seed)}",
            f"{'─' * 60}",
            f"  Side A win rate : {self.win_rate_a():.1%}",
            f"  Side B win rate : {self.win_rate_b():.1%}",
            f"  Draw rate       : {self.draw_rate():.1%}",
            f"  Avg turns       : {self.avg_turns():.1f}",
            f"{'─' * 60}",
            f"  Unit performance (avg per run):",
        ]
        for mid, s in sorted(us.items(), key=lambda x: x[1]["side"]):
            lines.append(
                f"  [{s['side']}] {s['name']} {s['variant']:<12} "
                f"surv={s['survival_rate']:.0%}  "
                f"dmg={s['avg_damage_dealt']:.1f}  "
                f"eff={s['efficiency']:.2f}"
            )
        lines.append(f"{'─' * 60}")
        return "\n".join(lines)


# ── Seed log writer ───────────────────────────────────────────────────────────

def _write_seed_log(results: MatchupResults, log_dir: str = "sim_logs") -> str:
    """
    Append one row per matchup to sim_logs/seed_log.csv.

    Columns:
        timestamp, batch_id,
        force_a, force_b, n_sims,
        combat_seed, force_a_seed, force_b_seed,
        win_rate_a, win_rate_b, draw_rate, avg_turns

    All three seeds are recorded so any run can be fully replayed:
      - combat_seed    → reproduces all dice rolls
      - force_a_seed   → reproduces force A composition
      - force_b_seed   → reproduces force B composition
    """
    os.makedirs(log_dir, exist_ok=True)
    log_path    = os.path.join(log_dir, "seed_log.csv")
    file_exists = os.path.exists(log_path)

    def _s(v): return str(v) if v is not None else ""

    row = {
        "timestamp":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "batch_id":     results.batch_id,
        "force_a":      results.force_a_name,
        "force_b":      results.force_b_name,
        "n_sims":       results.n_simulations,
        "combat_seed":  results.base_seed,
        "force_a_seed": _s(results.force_a_seed),
        "force_b_seed": _s(results.force_b_seed),
        "win_rate_a":   f"{results.win_rate_a():.4f}",
        "win_rate_b":   f"{results.win_rate_b():.4f}",
        "draw_rate":    f"{results.draw_rate():.4f}",
        "avg_turns":    f"{results.avg_turns():.2f}",
    }

    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv_module.DictWriter(f, fieldnames=list(row.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    return log_path


# ── Public entry point ────────────────────────────────────────────────────────

def run_matchup(
    force_a:       List[SimUnit],
    force_b:       List[SimUnit],
    force_a_name:  str           = "Force A",
    force_b_name:  str           = "Force B",
    n_simulations: int           = DEFAULT_SIMULATIONS,
    base_seed:     Optional[int] = None,
    force_a_seed:  Optional[int] = None,
    force_b_seed:  Optional[int] = None,
    verbose:       bool          = False,
    log:           bool          = True,
) -> MatchupResults:
    """
    Run N simulations of Force A vs Force B.

    Seed behaviour
    ──────────────
    base_seed=None (default)
        Generates a fresh random combat seed each call — two runs of the
        same matchup will produce different results. The seed is logged so
        you can replay exact results later by passing it back in.

    base_seed=<int>
        Uses that exact seed for fully deterministic output. Pass the
        combat_seed value from a previous log row to replay it exactly.

    force_a_seed / force_b_seed
        Seeds used when building the forces via build_force_by_role().
        Pass None (default) for manually constructed forces.
        Logged alongside combat_seed so the full run is reproducible.

    Args:
        force_a / force_b  : lists of SimUnit (reset to full health each run)
        n_simulations      : number of Monte Carlo passes
        base_seed          : combat RNG seed (random if None)
        force_a/b_seed     : force composition seeds for logging
        verbose            : print progress every 100 runs
        log                : write result row to sim_logs/seed_log.csv

    Returns:
        MatchupResults with all run data, aggregate helpers, and seed info
    """
    if base_seed is None:
        base_seed = random.randint(0, 2**31 - 1)

    batch_id = str(uuid.uuid4())[:8]

    results = MatchupResults(
        force_a_name  = force_a_name,
        force_b_name  = force_b_name,
        n_simulations = n_simulations,
        base_seed     = base_seed,
        batch_id      = batch_id,
        force_a_seed  = force_a_seed,
        force_b_seed  = force_b_seed,
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

    if log:
        log_path = _write_seed_log(results)
        if verbose:
            print(f"  Seed log → {log_path}")

    return results
