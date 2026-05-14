"""
Simulation constants — hit tables, range definitions, role mappings.
Now includes fixed Clan benchmark stars for IS evaluation.
"""

# ── Range bands ───────────────────────────────────────────────────────────────
SHORT  = 0
MEDIUM = 1
LONG   = 2

RANGE_NAMES = {SHORT: "Short", MEDIUM: "Medium", LONG: "Long"}

# ── 2d6 probability table ─────────────────────────────────────────────────────
_2D6_GTE = {
    2: 36, 3: 35, 4: 33, 5: 30,
    6: 26, 7: 21, 8: 15, 9: 10,
    10: 6, 11: 3, 12: 1,
}

def hit_probability(target_number: int) -> float:
    if target_number <= 2:  return 1.0
    if target_number >= 13: return 0.0
    return _2D6_GTE[target_number] / 36.0

HIT_PROB_TABLE = {tn: hit_probability(tn) for tn in range(2, 14)}

# ── To-hit constants ─────────────────────────────────────────────────────────
BASE_TO_HIT    = 3
SKILL_MODIFIER = 4

RANGE_TO_HIT_MOD = {
    SHORT:  1,
    MEDIUM: 2,
    LONG:   4,
}

# ── Role → preferred range ───────────────────────────────────────────────────
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

DEFAULT_PREFERRED_RANGE = MEDIUM

DEFAULT_SIMULATIONS = 750
MAX_TURNS = 50
STARTING_RANGE = MEDIUM


# ─────────────────────────────────────────────────────────────
# CLAN BENCHMARK STARS
# Nested by OP then tier. Tier selected at runtime based on IS lance PV:
#   T1: IS PV   0-133  →  Clan stars 100-133 PV
#   T2: IS PV 134-166  →  Clan stars 133-166 PV
#   T3: IS PV 167-200  →  Clan stars  ≤200 PV
# All names match the CSV 'name' column exactly.
# ─────────────────────────────────────────────────────────────

CLAN_STARS = {
    "OP1_BALANCED": {
        "T1": [                          # 133 PV — light snipers, dual ECM
            "Puma (Adder) K",            # Sniper  PV=25
            "Puma (Adder) B",            # Sniper  PV=28
            "Koshi (Mist Lynx) C",       # Striker PV=29  ECM
            "Uller (Kit Fox) C",         # Striker PV=27  ECM
            "Dasher (Fire Moth) I",      # Sniper  PV=24
        ],
        "T2": [                          # 152 PV — medium snipers, missile support
            "Ryoken (Stormcrow) (Attwater)",  # Sniper       PV=32
            "Black Hawk (Nova) B",            # Sniper       PV=32
            "Loki (Hellbringer) D",           # Striker      PV=30
            "Uller (Kit Fox) V",              # Missile Boat PV=28
            "Puma (Adder) Prime",             # Sniper       PV=30
        ],
        "T3": [                          # 187 PV — heavy snipers, ECM striker
            "Mad Cat (Timber Wolf) B",        # Sniper       PV=48
            "Ryoken (Stormcrow) (Attwater)",  # Sniper       PV=32
            "Black Hawk (Nova) U",            # Striker      PV=39  ECM
            "Thor (Summoner) A",              # Sniper       PV=40
            "Uller (Kit Fox) V",              # Missile Boat PV=28
        ],
    },

    "OP2_LONG_RANGE": {
        "T1": [                          # 133 PV — light sniper line, ECM support
            "Dark Crow 2",               # Sniper       PV=30
            "Puma (Adder) K",            # Sniper       PV=25
            "Puma (Adder) J",            # Sniper       PV=28
            "Arbalest 2",                # Missile Boat PV=24  ECM
            "Uller (Kit Fox) Prime",     # Sniper       PV=26
        ],
        "T2": [                          # 158 PV — Mad Cat anchor, sniper line
            "Mad Cat (Timber Wolf) B",   # Sniper       PV=48
            "Vulture (Mad Dog) C",       # Sniper       PV=33
            "Puma (Adder) B",            # Sniper       PV=28
            "Puma (Adder) K",            # Sniper       PV=25
            "Arbalest 2",                # Missile Boat PV=24  ECM
        ],
        "T3": [                          # 199 PV — Mad Cat + assault fire support
            "Mad Cat (Timber Wolf) B",   # Sniper       PV=48
            "Masakari (Warhawk) B",      # Brawler      PV=52
            "Vulture (Mad Dog) C",       # Sniper       PV=33
            "Loki (Hellbringer) B",      # Striker      PV=35
            "Rifleman IIC 2",            # Sniper       PV=31
        ],
    },

    "OP3_FAST_STRIKE": {
        "T1": [                          # 133 PV — light speed swarm, ECM dasher
            "Fire Falcon G",             # Striker PV=29
            "Hankyu (Arctic Cheetah) B", # Striker PV=28
            "Locust IIC 3",              # Striker PV=28
            "Piranha 2",                 # Striker PV=24
            "Dasher (Fire Moth) B",      # Striker PV=24  ECM
        ],
        "T2": [                          # 166 PV — medium fast movers, ECM Dragonfly
            "Fenris (Ice Ferret) B",     # Striker     PV=40
            "Goshawk (Vapor Eagle) 6",   # Skirmisher  PV=35
            "Dragonfly (Viper) U",       # Striker     PV=35  ECM
            "Hankyu (Arctic Cheetah) H", # Striker     PV=29
            "Fire Falcon D",             # Striker     PV=27
        ],
        "T3": [                          # 200 PV — Mad Cat D anchor, fast strike force
            "Mad Cat (Timber Wolf) D",        # Skirmisher PV=51
            "Fenris (Ice Ferret) I",           # Scout      PV=43
            "Black Hawk (Nova) U",             # Striker    PV=39  ECM
            "Loki (Hellbringer) B",            # Striker    PV=35
            "Ryoken (Stormcrow) (Attwater)",   # Sniper     PV=32
        ],
    },

    "OP4_ASSAULT": {
        "T1": [                          # 132 PV — budget brawlers, Crimson Hawk thread
            "Arbalest 3",                # Brawler  PV=30
            "Corvis",                    # Brawler  PV=29
            "Puma (Adder) H",            # Brawler  PV=28
            "Hunchback IIC 5",           # Ambusher PV=25
            "Crimson Hawk 3",            # Brawler  PV=20
        ],
        "T2": [                          # 166 PV — triple ECM assault, Crimson Hawk thread
            "Nova Cat D",                # Brawler     PV=40
            "Ursus 3",                   # Juggernaut  PV=38  ECM
            "Hunchback IIC 4",           # Brawler     PV=35  ECM
            "Cougar H",                  # Brawler     PV=33  ECM
            "Crimson Hawk 3",            # Brawler     PV=20
        ],
        "T3": [                          # 200 PV — Mad Cat M anchor, assault wall
            "Mad Cat (Timber Wolf) M",   # Brawler     PV=50
            "Warhammer IIC 11",          # Juggernaut  PV=48
            "Doom Courser B",            # Juggernaut  PV=42
            "Nova Cat M",                # Juggernaut  PV=40
            "Crimson Hawk 3",            # Brawler     PV=20
        ],
    },
}