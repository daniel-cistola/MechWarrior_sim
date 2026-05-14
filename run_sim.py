"""
run_sim.py — BattleTech Alpha Strike simulator entry point.

Supports:
- Fixed Clan benchmark stars
- IS behavior-based lance generation
- Per-matchup evaluation (independent, all 750 sims)
- Sequential campaign evaluation (IS lance fights all 4 stars in order)
"""

import re
import pandas as pd
import sys
import os
import random

sys.path.insert(0, os.path.dirname(__file__))

from sim import SimUnit, run_matchup, run_campaign
from sim.constants import CLAN_STARS


# ─────────────────────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────────────────────

def load_mechs(csv_path: str) -> pd.DataFrame:
    return pd.read_csv(csv_path)


def find_mech(df: pd.DataFrame, name: str) -> SimUnit:
    match = df[df["name"].str.contains(re.escape(name), case=False, na=False)]
    if match.empty:
        raise ValueError(f"No mech found matching '{name}'")
    return SimUnit.from_row(match.iloc[0])


# ─────────────────────────────────────────────────────────────
# IS LANCE BUILDER (STRATEGY-BASED)
# ─────────────────────────────────────────────────────────────

def build_is_lance(
    df: pd.DataFrame,
    strategy: str,
    max_points: int = 200,
    force_seed: int | None = None,
):
    rng = random.Random(force_seed)

    pool = df[df["technology"] == "Inner Sphere"].copy()

    strategies = {
        "brawler":    ["Brawler", "Juggernaut", "Striker", "Brawler"],
        "sniper":     ["Sniper", "Sniper", "Striker", "Scout"],
        "skirmisher": ["Skirmisher", "Striker", "Scout", "Striker"],
        "balanced":   ["Brawler", "Sniper", "Striker", "Scout"],
    }

    roles = strategies.get(strategy, strategies["balanced"])

    force = []
    budget = max_points

    for role in roles:
        candidates = pool[pool["role"] == role]

        if candidates.empty:
            continue

        candidates = candidates.sample(
            frac=1,
            random_state=rng.randint(0, 10**9)
        )

        picked = None
        for _, row in candidates.iterrows():
            pv = int(row["bf_point_value"])
            if pv <= budget:
                picked = SimUnit.from_row(row)
                budget -= pv
                break

        if picked:
            force.append(picked)

    # Fallback fill — spend remaining budget on anything that fits
    remaining = pool.sample(frac=1, random_state=rng.randint(0, 10**9))
    for _, row in remaining.iterrows():
        if len(force) >= 4:
            break
        pv = int(row["bf_point_value"])
        if pv <= budget:
            force.append(SimUnit.from_row(row))
            budget -= pv

    return force, force_seed


# ─────────────────────────────────────────────────────────────
# CLAN STAR BUILDER (FIXED OPPONENTS)
# ─────────────────────────────────────────────────────────────

def build_clan_star(df: pd.DataFrame, star_name: str, tier: str) -> list[SimUnit]:
    """Build a fixed Clan star for the given OP and tier."""
    units = []
    for mech_name in CLAN_STARS[star_name][tier]:
        units.append(find_mech(df, mech_name))
    return units


def select_tier(is_lance: list[SimUnit]) -> str:
    """
    Select Clan star tier based on IS lance total PV.
        0-133  → T1
        134-166 → T2
        167+    → T3
    """
    total_pv = sum(u.bf_point_value for u in is_lance)
    if total_pv <= 133:
        return "T1"
    elif total_pv <= 166:
        return "T2"
    else:
        return "T3"

# ─────────────────────────────────────────────────────────────
# DISPLAY HELPERS
# ─────────────────────────────────────────────────────────────

def print_force(label: str, units: list[SimUnit], seed: int = None):
    seed_str = f"  (force seed: {seed})" if seed is not None else ""
    print(f"\n  {label}:{seed_str}")
    total_pv = sum(u.bf_point_value for u in units)
    for u in units:
        ecm_tag = ""
        if u.has_ecm:    ecm_tag += " ECM"
        if u.has_aecm:   ecm_tag += " AECM"
        if u.has_stealth: ecm_tag += " STL"
        print(
            f"    {u.name:<45} [{u.role:<12}] "
            f"PV={u.bf_point_value:>3}  HP={u.max_health}  "
            f"Dmg S/M/L={u.bf_damage_short}/{u.bf_damage_medium}/{u.bf_damage_long}  "
            f"Move={u.move}\"  TMM={u.bf_tmm}{ecm_tag}"
        )
    print(f"    {'Total PV':>38}: {total_pv}")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":

    csv_path = "battlemechs_sim_ready.csv"
    if not os.path.exists(csv_path):
        csv_path = "/mnt/user-data/uploads/alpha_strike_units.csv"

    df = pd.read_csv(csv_path)
    print(f"{len(df)} mechs loaded")

    # ── Choose IS strategy ─────────────────────────────────────
    strategy = "balanced"
    force_seed = None    # set an int here to lock the IS lance composition

    is_lance, is_seed = build_is_lance(
        df,
        strategy=strategy,
        max_points=200,
        force_seed=force_seed,
    )
    tier = select_tier(is_lance)
    print(f"\nIS Lance PV: {sum(u.bf_point_value for u in is_lance)}  →  Clan tier: {tier}")
    
    print(f"\nIS Lance ({strategy} strategy):")
    print_force("Side A", is_lance, is_seed)

    # ── Build all Clan stars once (reused across matchups and campaign) ────────
    stage_order = list(CLAN_STARS.keys())   # fixed: OP1 → OP2 → OP3 → OP4

    clan_forces: dict[str, list[SimUnit]] = {}
    print("\nClan benchmark stars:")
    for star_name in stage_order:
        clan_forces[star_name] = build_clan_star(df, star_name, tier)
        print_force(star_name, clan_forces[star_name])

    # ═══════════════════════════════════════════════════════════
    # PART 1 — Independent matchups (existing behaviour)
    # Each matchup runs all 750 simulations fresh.
    # ═══════════════════════════════════════════════════════════

    print("\n\n" + "=" * 64)
    print("  PART 1 — INDEPENDENT MATCHUPS")
    print("  (IS lance vs each Clan star, 750 fresh sims each)")
    print("=" * 64)

    for star_name in stage_order:
        print(f"\n=== {star_name} ===")
        result = run_matchup(
            force_a      = is_lance,
            force_b      = clan_forces[star_name],
            force_a_name = f"IS ({strategy})",
            force_b_name = star_name,
            n_simulations = 750,
            force_a_seed  = is_seed,
            verbose       = False,
        )
        print(result.summary())

    # ═══════════════════════════════════════════════════════════
    # PART 2 — Sequential campaign
    # IS lance must beat OP1, then OP2, then OP3, then OP4 in order.
    # Full repair between stages. Eliminated = campaign ends.
    # ═══════════════════════════════════════════════════════════

    print("\n\n" + "=" * 64)
    print("  PART 2 — SEQUENTIAL CAMPAIGN")
    print("  (IS lance must beat all 4 stars in order)")
    print("  (Full repair between stages — elimination ends campaign)")
    print("=" * 64)

    campaign = run_campaign(
        force_a      = is_lance,
        clan_forces  = clan_forces,
        stage_order  = stage_order,
        force_a_name = f"IS ({strategy})",
        n_simulations = 750,
        force_a_seed  = is_seed,
        verbose       = False,
    )

    print(f"\n{campaign.summary()}")