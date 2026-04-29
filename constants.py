"""
Simulation constants — hit tables, range definitions, role mappings.
All pure data, no logic.
"""

# ── Range bands ───────────────────────────────────────────────────────────────
SHORT  = 0
MEDIUM = 1
LONG   = 2

RANGE_NAMES = {SHORT: "Short", MEDIUM: "Medium", LONG: "Long"}

# ── 2d6 probability of rolling >= N (the Alpha Strike hit table) ──────────────
# Source: there are 36 possible outcomes on 2d6.
# P(>= N) = ways_to_roll_N_or_higher / 36
_2D6_GTE = {
    2:  36, 3:  35, 4:  33, 5:  30,
    6:  26, 7:  21, 8:  15, 9:  10,
    10:  6, 11:  3, 12:  1,
}

def hit_probability(target_number: int) -> float:
    """Return P(hit) given a 2d6 target number."""
    if target_number <= 2:  return 1.0
    if target_number >= 13: return 0.0
    return _2D6_GTE[target_number] / 36.0

# Precomputed lookup for speed
HIT_PROB_TABLE = {tn: hit_probability(tn) for tn in range(2, 14)}

# ── To-hit modifiers ──────────────────────────────────────────────────────────
BASE_TO_HIT    = 3   # Alpha Strike base target number
SKILL_MODIFIER = 4   # Standard (Green=5, Regular=4, Veteran=3, Elite=2)

RANGE_TO_HIT_MOD = {
    SHORT:  1,
    MEDIUM: 2,
    LONG:   4,
}

# ── Role → preferred engagement range ────────────────────────────────────────
# Drives the range state machine each turn.
ROLE_PREFERRED_RANGE = {
    "Striker":     SHORT,
    "Brawler":     SHORT,
    "Juggernaut":  SHORT,
    "Ambusher":    SHORT,
    "Skirmisher":  MEDIUM,
    "Missile Boat": MEDIUM,
    "Scout":       MEDIUM,
    "Sniper":      LONG,
}

DEFAULT_PREFERRED_RANGE = MEDIUM  # fallback for unknown roles

# ── Simulation defaults ───────────────────────────────────────────────────────
DEFAULT_SIMULATIONS = 750   # per matchup
MAX_TURNS           = 24    # safety cutoff — prevents infinite loops on draws
STARTING_RANGE      = MEDIUM
