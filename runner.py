"""
Monte Carlo runner — runs N simulations of Force A vs Force B
and returns structured results aligned to the SIM_RUN / UNIT_RESULT schema.

Also contains the campaign runner — runs one IS lance sequentially through
a fixed list of Clan opponent stages, with full repair between each stage.
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

    # Reset all units to full health — this is the "full repair" between stages
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
                f"  [{s['side']}] {s['name']:<45} "
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


# ── Public entry point — single matchup ──────────────────────────────────────

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


# ═════════════════════════════════════════════════════════════════════════════
# CAMPAIGN RUNNER
# Runs one IS lance sequentially through a fixed list of Clan opponent stages.
# Full repair (complete reset) is applied between every stage.
# If the IS lance is eliminated (winner != "A") the campaign ends at that stage.
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class CampaignRun:
    """
    Result of one simulation's full campaign attempt.

    stages_entered  — how many stages this sim reached (always >= 1)
    stages_won      — how many stages the IS lance won (0 = fell at stage 1)
    eliminated_at   — name of the stage where IS was stopped, None if full clear
    stage_winners   — "A" / "B" / "Draw" for each stage that was fought
    """
    sim_index:      int
    stages_entered: int
    stages_won:     int
    eliminated_at:  Optional[str]
    stage_winners:  List[str]


@dataclass
class CampaignResults:
    """
    Aggregate results across N campaign simulations.

    stage_names  — the fixed stage order used for this campaign
    """
    force_name:    str
    stage_names:   List[str]
    n_simulations: int
    base_seed:     int
    force_seed:    Optional[int]
    runs:          List[CampaignRun] = field(default_factory=list)

    def stage_stats(self) -> List[Dict[str, Any]]:
        """
        Per-stage breakdown across all simulations.

        entered  — sims that reached this stage (always n_simulations for stage 0)
        won      — sims that won this stage and advanced
        win_pct  — won / entered  (conditional: given you got here, did you win?)
        cum_pct  — won / n_simulations  (unconditional pass-through rate)
        """
        stats = []
        for i, name in enumerate(self.stage_names):
            entered = sum(1 for r in self.runs if r.stages_entered > i)
            won     = sum(1 for r in self.runs if r.stages_won > i)
            win_pct = won / entered if entered > 0 else 0.0
            cum_pct = won / self.n_simulations
            stats.append({
                "stage":   name,
                "entered": entered,
                "won":     won,
                "win_pct": win_pct,
                "cum_pct": cum_pct,
            })
        return stats

    def full_clear_rate(self) -> float:
        """Fraction of simulations that won every stage."""
        clears = sum(1 for r in self.runs if r.stages_won == len(self.stage_names))
        return clears / self.n_simulations

    def elimination_breakdown(self) -> Dict[str, int]:
        """
        Count how many simulations ended at each stage (including None = full clear).
        Useful for seeing which stage is the biggest wall.
        """
        breakdown: Dict[str, int] = {"FULL CLEAR": 0}
        for name in self.stage_names:
            breakdown[name] = 0
        for r in self.runs:
            key = r.eliminated_at if r.eliminated_at is not None else "FULL CLEAR"
            breakdown[key] = breakdown.get(key, 0) + 1
        return breakdown

    def summary(self) -> str:
        """Human-readable campaign summary."""
        stats = self.stage_stats()
        elim  = self.elimination_breakdown()
        w     = 64

        lines = [
            "=" * w,
            f"  CAMPAIGN RESULTS — {self.force_name}",
            f"  {self.n_simulations} simulations  |  base seed: {self.base_seed}",
            f"  Stage order: {' → '.join(self.stage_names)}",
            "=" * w,
            f"  {'Stage':<22} {'Entered':>8} {'Won':>6} {'Win%':>7} {'Cumulative%':>12}",
            f"  {'-'*22} {'-'*8} {'-'*6} {'-'*7} {'-'*12}",
        ]

        for s in stats:
            lines.append(
                f"  {s['stage']:<22} {s['entered']:>8} {s['won']:>6} "
                f"{s['win_pct']:>7.1%} {s['cum_pct']:>12.1%}"
            )

        lines.append(f"  {'─'*22} {'─'*8} {'─'*6} {'─'*7} {'─'*12}")
        lines.append(f"  Full campaign clear: {self.full_clear_rate():.1%}")
        lines.append("")
        lines.append(f"  Elimination breakdown:")

        for stage in self.stage_names:
            count = elim.get(stage, 0)
            pct   = count / self.n_simulations
            bar   = "█" * int(pct * 30)
            lines.append(f"  Fell at {stage:<18} {count:>5} ({pct:>5.1%})  {bar}")

        full = elim.get("FULL CLEAR", 0)
        pct  = full / self.n_simulations
        bar  = "█" * int(pct * 30)
        lines.append(f"  {'FULL CLEAR':<26} {full:>5} ({pct:>5.1%})  {bar}")
        lines.append("=" * w)

        return "\n".join(lines)


# ── Campaign log writer ───────────────────────────────────────────────────────

def _write_campaign_log(
    results: CampaignResults,
    log_dir: str = "sim_logs",
) -> str:
    """
    Append one row per campaign batch to sim_logs/campaign_log.csv.

    Columns: timestamp, force_name, force_seed, n_sims, base_seed,
             entered_s1..s4, won_s1..s4, win_pct_s1..s4, full_clear_pct
    """
    os.makedirs(log_dir, exist_ok=True)
    log_path    = os.path.join(log_dir, "campaign_log.csv")
    file_exists = os.path.exists(log_path)

    stats = results.stage_stats()

    row: Dict[str, Any] = {
        "timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "force_name":  results.force_name,
        "force_seed":  str(results.force_seed) if results.force_seed is not None else "",
        "n_sims":      results.n_simulations,
        "base_seed":   results.base_seed,
    }
    for i, s in enumerate(stats, start=1):
        row[f"entered_s{i}"] = s["entered"]
        row[f"won_s{i}"]     = s["won"]
        row[f"win_pct_s{i}"] = f"{s['win_pct']:.4f}"

    row["full_clear_pct"] = f"{results.full_clear_rate():.4f}"

    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv_module.DictWriter(f, fieldnames=list(row.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    return log_path


# ── Public entry point — campaign ─────────────────────────────────────────────

def run_campaign(
    force_a:       List[SimUnit],
    clan_forces:   Dict[str, List[SimUnit]],
    stage_order:   List[str],
    force_a_name:  str           = "IS Lance",
    n_simulations: int           = DEFAULT_SIMULATIONS,
    base_seed:     Optional[int] = None,
    force_a_seed:  Optional[int] = None,
    verbose:       bool          = False,
    log:           bool          = True,
) -> CampaignResults:
    """
    Run N campaign simulations.

    Each simulation advances the IS lance through stage_order sequentially.
    Full repair is applied before every stage (_run_single resets all units).
    The campaign ends when the IS lance fails to win (B win or Draw = elimination).

    Seed scheme
    ───────────
    Each stage in each simulation gets a unique, deterministic seed:
        stage_seed = base_seed + (sim_index * len(stage_order)) + stage_index

    This ensures:
      - No two stages share a seed within the same simulation
      - The same base_seed always produces the same campaign results
      - Stage seeds don't overlap across simulations

    Args:
        force_a       : IS lance (SimUnit list) — reset automatically each stage
        clan_forces   : dict mapping stage name → Clan SimUnit list
        stage_order   : fixed sequence of stage names to fight through
        force_a_name  : label for the IS force (used in output)
        n_simulations : number of Monte Carlo campaign runs
        base_seed     : master RNG seed (random if None)
        force_a_seed  : seed used to build force_a (for logging only)
        verbose       : print progress every 100 simulations
        log           : write results to sim_logs/campaign_log.csv

    Returns:
        CampaignResults with per-stage stats and full summary
    """
    if base_seed is None:
        base_seed = random.randint(0, 2**31 - 1)

    n_stages = len(stage_order)

    results = CampaignResults(
        force_name    = force_a_name,
        stage_names   = list(stage_order),
        n_simulations = n_simulations,
        base_seed     = base_seed,
        force_seed    = force_a_seed,
    )

    for i in range(n_simulations):
        if verbose and i % 100 == 0:
            print(f"  Campaign run {i}/{n_simulations}...")

        stages_entered = 0
        stages_won     = 0
        eliminated_at  = None
        stage_winners  = []

        for j, stage_name in enumerate(stage_order):
            clan_force = clan_forces[stage_name]
            stage_seed = base_seed + (i * n_stages) + j
            stages_entered += 1

            sim_run = _run_single(
                force_a      = force_a,
                force_b      = clan_force,
                force_a_name = force_a_name,
                force_b_name = stage_name,
                seed         = stage_seed,
            )

            stage_winners.append(sim_run.winner)

            if sim_run.winner == "A":
                stages_won += 1
            else:
                # IS was eliminated — campaign ends here
                eliminated_at = stage_name
                break

        results.runs.append(CampaignRun(
            sim_index      = i,
            stages_entered = stages_entered,
            stages_won     = stages_won,
            eliminated_at  = eliminated_at,
            stage_winners  = stage_winners,
        ))

    if log:
        log_path = _write_campaign_log(results)
        if verbose:
            print(f"  Campaign log → {log_path}")

    return results