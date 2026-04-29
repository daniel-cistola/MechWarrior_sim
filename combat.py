"""
Combat resolution — one full turn of Alpha Strike simulation.

Phases each turn:
  1. Initiative   — 2d6 per side, winner declared (affects future tie-breaking)
  2. Range contest — fastest survivor on each side contests range band
  3. Target selection — each unit picks best target (role-aware)
  4. Attack resolution — simultaneous hit probability checks
  5. Damage application — all damage lands at once
  6. Casualty check — dead units removed

No special abilities in Phase 1. Hooks marked with # [PHASE2] for later.
"""

from __future__ import annotations
import random
from typing import List, Tuple, Optional

from sim.constants import (
    SHORT, MEDIUM, LONG,
    BASE_TO_HIT, SKILL_MODIFIER,
    RANGE_TO_HIT_MOD, HIT_PROB_TABLE,
    ROLE_PREFERRED_RANGE, DEFAULT_PREFERRED_RANGE,
)
from sim.unit import SimUnit


# ── Initiative ────────────────────────────────────────────────────────────────

def roll_initiative() -> Tuple[int, int]:
    """Roll 2d6 for each side. Returns (side_a_roll, side_b_roll)."""
    return (
        random.randint(1, 6) + random.randint(1, 6),
        random.randint(1, 6) + random.randint(1, 6),
    )


# ── Range state machine ───────────────────────────────────────────────────────

def _side_preferred_range(units: List[SimUnit]) -> int:
    """
    Determine a side's preferred range based on surviving units.
    Uses the preference of the fastest surviving unit — the unit most
    capable of dictating engagement distance sets the agenda.
    """
    alive = [u for u in units if u.alive]
    if not alive:
        return DEFAULT_PREFERRED_RANGE
    # Fastest unit drives range preference
    fastest = max(alive, key=lambda u: u.move)
    return fastest.preferred_range


def _side_max_move(units: List[SimUnit]) -> int:
    """Return the highest move value among surviving units on a side."""
    alive = [u for u in units if u.alive]
    return max((u.move for u in alive), default=0)


def contest_range(
    current_range: int,
    side_a: List[SimUnit],
    side_b: List[SimUnit],
    rng: random.Random,
) -> int:
    """
    Contest the range band for this turn.

    Each side's fastest unit pulls range toward their preferred band.
    The side with higher max move wins contested transitions.
    Ties are broken randomly. Range changes by at most one band per turn.

    Returns the new range band (SHORT=0, MEDIUM=1, LONG=2).
    """
    pref_a = _side_preferred_range(side_a)
    pref_b = _side_preferred_range(side_b)

    # Each side votes to move range toward their preference
    vote_a = _range_vote(current_range, pref_a)  # -1, 0, or +1
    vote_b = _range_vote(current_range, pref_b)

    if vote_a == 0 and vote_b == 0:
        return current_range   # both sides satisfied

    if vote_a == vote_b:
        return current_range + vote_a  # rare: both want the same direction

    # Contested — fastest unit wins; tie broken by coin flip
    speed_a = _side_max_move(side_a)
    speed_b = _side_max_move(side_b)

    if speed_a > speed_b:
        winner_vote = vote_a
    elif speed_b > speed_a:
        winner_vote = vote_b
    else:
        winner_vote = rng.choice([vote_a, vote_b])

    new_range = current_range + winner_vote
    return max(SHORT, min(LONG, new_range))   # clamp to valid bands


def _range_vote(current: int, preferred: int) -> int:
    """Return direction unit wants to move range: -1 (closer), 0 (stay), +1 (farther)."""
    if preferred < current: return -1
    if preferred > current: return +1
    return 0


# ── Target selection ──────────────────────────────────────────────────────────

def select_target(
    attacker: SimUnit,
    enemies: List[SimUnit],
    current_range: int,
) -> Optional[SimUnit]:
    """
    Role-aware target selection.

    Phase 1 logic:
      - All roles: prefer the highest point-value living enemy
        (proxy for "biggest threat")
      - Sniper: among enemies with damage at current range, pick highest PV
      - Striker/Brawler: prefer lowest-health enemy (finish them off)

    Returns None if no valid targets exist.

    [PHASE2] Add: preferred target type by role, C3 network bonuses,
                  flanking targets, last-known position tracking.
    """
    alive_enemies = [e for e in enemies if e.alive]
    if not alive_enemies:
        return None

    # Filter to enemies that can meaningfully be engaged
    # (i.e., the attacker has non-zero damage at this range)
    attacker_dmg = attacker.damage_at_range(current_range)
    if attacker_dmg == 0:
        # No damage at this range — still pick a target, just won't hurt
        # [PHASE2] Could choose not to fire instead
        pass

    role = attacker.role

    if role in ("Striker", "Brawler", "Juggernaut", "Ambusher"):
        # Prioritize damaged targets — maximize kills
        return min(alive_enemies, key=lambda e: e.health)

    if role == "Sniper":
        # Prioritize highest-value target
        return max(alive_enemies, key=lambda e: e.bf_point_value)

    if role in ("Skirmisher", "Scout"):
        # Prioritize weakest target for quick kills, support the team
        return min(alive_enemies, key=lambda e: e.health)

    # Default: highest point value (Missile Boat, unknown roles)
    return max(alive_enemies, key=lambda e: e.bf_point_value)


# ── Attack resolution ─────────────────────────────────────────────────────────

def calculate_to_hit(
    attacker: SimUnit,
    target: SimUnit,
    current_range: int,
) -> int:
    """
    Calculate the 2d6 target number to hit.

    Formula:
        TN = BASE (3) + SKILL (4) + range_modifier + target_TMM

    Returns an integer target number. Hit if 2d6 roll >= TN.

    [PHASE2] Add: terrain modifier, ECM (+2), Stealth (+2), size modifier,
                  attacker movement penalty, C3 network bonus (-1).
    """
    tn = (
        BASE_TO_HIT
        + SKILL_MODIFIER
        + RANGE_TO_HIT_MOD[current_range]
        + target.bf_tmm
    )
    # [PHASE2] + terrain_modifier
    # [PHASE2] - 1 if attacker has C3 network
    # [PHASE2] + 2 if target has ECM
    # [PHASE2] + 2 if target has Stealth
    return tn


def resolve_attack(
    attacker: SimUnit,
    target: SimUnit,
    current_range: int,
    rng: random.Random,
) -> Tuple[bool, int]:
    """
    Resolve a single attack. Returns (hit: bool, damage: int).

    Damage is only non-zero on a hit. Damage comes from attacker's
    stat at the current range band.
    """
    tn     = calculate_to_hit(attacker, target, current_range)
    prob   = HIT_PROB_TABLE.get(tn, 0.0)
    hit    = rng.random() < prob
    damage = attacker.damage_at_range(current_range) if hit else 0
    return hit, damage


# ── Full turn resolution ──────────────────────────────────────────────────────

class TurnResult:
    """Lightweight record of what happened in one turn."""
    __slots__ = ("turn_number", "range_band", "initiative_winner",
                 "attacks")

    def __init__(self, turn_number, range_band, initiative_winner):
        self.turn_number       = turn_number
        self.range_band        = range_band
        self.initiative_winner = initiative_winner
        self.attacks           = []   # list of (attacker_id, target_id, hit, damage)


def resolve_turn(
    turn_number: int,
    side_a: List[SimUnit],
    side_b: List[SimUnit],
    current_range: int,
    rng: random.Random,
) -> Tuple[int, TurnResult]:
    """
    Resolve one full turn of combat.

    Returns:
        new_range  — updated range band after this turn's contest
        turn_result — record of all events this turn
    """
    # 1. Initiative
    roll_a, roll_b = roll_initiative()
    # Reroll exact ties
    while roll_a == roll_b:
        roll_a, roll_b = roll_initiative()
    initiative_winner = "A" if roll_a > roll_b else "B"

    # 2. Range contest
    new_range = contest_range(current_range, side_a, side_b, rng)

    result = TurnResult(turn_number, new_range, initiative_winner)

    # 3. Build attack queue — each living unit picks a target
    attack_queue = []   # (attacker, target)

    for unit in side_a:
        if unit.alive:
            target = select_target(unit, side_b, new_range)
            if target:
                attack_queue.append((unit, target))

    for unit in side_b:
        if unit.alive:
            target = select_target(unit, side_a, new_range)
            if target:
                attack_queue.append((unit, target))

    # 4. Resolve all attacks, collect pending damage
    # Damage is applied AFTER all attacks are resolved (simultaneous fire)
    pending_damage: dict[int, int] = {}   # mul_id → total incoming damage

    for attacker, target in attack_queue:
        hit, damage = resolve_attack(attacker, target, new_range, rng)
        result.attacks.append((attacker.mul_id, target.mul_id, hit, damage))

        if hit and damage > 0:
            pending_damage[target.mul_id] = (
                pending_damage.get(target.mul_id, 0) + damage
            )
            attacker.damage_dealt += damage

    # 5. Apply all damage simultaneously
    all_units = side_a + side_b
    unit_map  = {u.mul_id: u for u in all_units}

    for uid, dmg in pending_damage.items():
        if uid in unit_map:
            unit_map[uid].apply_damage(dmg)

    # 6. Tick turns_active for surviving units
    for unit in all_units:
        if unit.alive:
            unit.turns_active += 1

    # [PHASE2] Heat step: units with bf_overheat > 0 can push for +damage
    # but accumulate heat tokens — skipped in Phase 1

    return new_range, result
