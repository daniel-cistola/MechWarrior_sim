"""
run_sim.py — Example entry point for the BattleTech Alpha Strike simulator.

Loads real mech data from battlemechs_sim_ready.csv and runs a few
illustrative matchups to verify the engine is working.
"""

import pandas as pd
import sys
import os

# Allow running from project root
sys.path.insert(0, os.path.dirname(__file__))

from sim import SimUnit, run_matchup


def load_mechs(csv_path: str) -> pd.DataFrame:
    return pd.read_csv(csv_path)


def find_mech(df: pd.DataFrame, name: str) -> SimUnit:
    """Look up a mech by name fragment and return a SimUnit."""
    match = df[df["name"].str.contains(name, case=False, na=False)]
    if match.empty:
        raise ValueError(f"No mech found matching '{name}'")
    row = match.iloc[0]
    return SimUnit.from_row(row)


def build_force_by_role(
    df: pd.DataFrame,
    roles: list[str],
    max_points: int = 200,
    technology: str = None,
    force_seed: int = None,
) -> tuple[list[SimUnit], int]:
    """
    Build a force by randomly selecting one mech per specified role
    within a point budget.

    Selection process per role slot:
      - Filter to mechs of the correct role (and technology if specified)
      - Shuffle the candidate pool using force_seed
      - Walk through shuffled candidates until one fits the remaining budget
      - If no mech fits the slot, skip it rather than bust the budget

    Args:
        df          : mech database (pre-filtered to BattleMechs 15-100t)
        roles       : list of role strings, one slot per entry
                      e.g. ["Brawler", "Sniper", "Striker", "Scout"]
        max_points  : total PV budget for the force
        technology  : optional filter — "Inner Sphere", "Clan", etc.
        force_seed  : RNG seed for reproducibility; random if None

    Returns:
        (force, seed) — the list of SimUnits and the seed used,
        so callers can log the seed and replay the exact composition later.
    """
    import random as _random

    if force_seed is None:
        force_seed = _random.randint(0, 2**31 - 1)

    rng = _random.Random(force_seed)

    # Apply technology filter once up front
    pool = df.copy()
    if technology:
        pool = pool[pool["technology"] == technology]

    force = []
    budget_remaining = max_points

    for role in roles:
        candidates = pool[pool["role"] == role].copy()
        if candidates.empty:
            continue   # no mechs of this role in pool — skip slot

        # Shuffle so every run picks a different mech from this role
        candidates = candidates.sample(frac=1, random_state=rng.randint(0, 2**31 - 1))

        # Walk shuffled candidates until one fits the remaining budget
        for _, row in candidates.iterrows():
            pv = int(row["bf_point_value"])
            if pv <= budget_remaining:
                force.append(SimUnit.from_row(row))
                budget_remaining -= pv
                break
        # If nothing fits, slot is skipped — keeps budget hard

    return force, force_seed


def print_force(name: str, units: list[SimUnit], seed: int = None):
    print(f"\n  {name}:" + (f"  (force seed: {seed})" if seed else ""))
    total_pv = sum(u.bf_point_value for u in units)
    for u in units:
        print(f"    {u.name} {u.variant:<14} "
              f"[{u.role:<12}] "
              f"PV={u.bf_point_value:>3}  "
              f"HP={u.max_health}  "
              f"Dmg S/M/L={u.bf_damage_short}/{u.bf_damage_medium}/{u.bf_damage_long}  "
              f"Move={u.move}\"  TMM={u.bf_tmm}")
    print(f"    {'Total PV':>38}: {total_pv}")


if __name__ == "__main__":
    csv_path = "battlemechs_sim_ready.csv"
    if not os.path.exists(csv_path):
        csv_path = "/mnt/user-data/uploads/alpha_strike_units.csv"

    print("Loading mech database...")
    df = pd.read_csv(csv_path)

    print(f"  {len(df)} mechs available\n")

    # ── Matchup 1: Classic 1v1 — Warhammer vs Marauder ───────────────────────
    print("=" * 55)
    print("MATCHUP 1: Warhammer vs Marauder (1v1 duel)")
    print("=" * 55)

    warhammer = find_mech(df, "Warhammer WHM-7A")
    marauder  = find_mech(df, "Marauder MAD-3R")

    print_force("Side A", [warhammer])
    print_force("Side B", [marauder])

    result1 = run_matchup(
        force_a       = [warhammer],
        force_b       = [marauder],
        force_a_name  = "Warhammer WHM-7A",
        force_b_name  = "Marauder MAD-3R",
        n_simulations = 750,
        verbose       = False,
    )
    print(f"\n{result1.summary()}")

    # ── Matchup 2: Lance vs Lance — Balanced IS vs Clan ──────────────────────
    print("\n" + "=" * 55)
    print("MATCHUP 2: IS Balanced Lance vs Clan Striker Lance")
    print("=" * 55)

    is_lance, is_seed = build_force_by_role(
        df,
        roles      = ["Brawler", "Sniper", "Striker", "Scout"],
        max_points = 200,
        technology = "Inner Sphere",
    )
    clan_lance, clan_seed = build_force_by_role(
        df,
        roles      = ["Striker", "Striker", "Sniper", "Scout"],
        max_points = 200,
        technology = "Clan",
    )

    print_force("Side A — IS Balanced", is_lance, is_seed)
    print_force("Side B — Clan Striker", clan_lance, clan_seed)

    result2 = run_matchup(
        force_a        = is_lance,
        force_b        = clan_lance,
        force_a_name   = "IS Balanced Lance",
        force_b_name   = "Clan Striker Lance",
        n_simulations  = 750,
        force_a_seed   = is_seed,
        force_b_seed   = clan_seed,
        verbose        = False,
    )
    print(f"\n{result2.summary()}")

    # ── Matchup 3: Equal point value — Sniper-heavy vs Brawler-heavy ─────────
    print("\n" + "=" * 55)
    print("MATCHUP 3: Sniper Lance vs Brawler Lance (~200pts each)")
    print("=" * 55)

    sniper_lance, sniper_seed = build_force_by_role(
        df,
        roles      = ["Sniper", "Sniper", "Sniper", "Scout"],
        max_points = 200,
    )
    brawler_lance, brawler_seed = build_force_by_role(
        df,
        roles      = ["Brawler", "Brawler", "Brawler", "Striker"],
        max_points = 200,
    )

    print_force("Side A — Sniper Lance", sniper_lance, sniper_seed)
    print_force("Side B — Brawler Lance", brawler_lance, brawler_seed)

    result3 = run_matchup(
        force_a        = sniper_lance,
        force_b        = brawler_lance,
        force_a_name   = "Sniper Lance",
        force_b_name   = "Brawler Lance",
        n_simulations  = 750,
        force_a_seed   = sniper_seed,
        force_b_seed   = brawler_seed,
        verbose        = False,
    )
    print(f"\n{result3.summary()}")
