# -*- coding: utf-8 -*-
"""
Created on Fri May  8 07:19:46 2026

@author: DJ and Perplexity
"""
from __future__ import annotations

import argparse
import random
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from sim import SimUnit, run_campaign, run_matchup
from sim.constants import CLAN_STARS


@dataclass
class StarExperimentRow:
    lance_id: str
    roster: str
    pv_total: int
    tier: str
    mode: str
    target_op: str
    screen_sims: int
    final_sims: int
    win_rate: float
    draw_rate: float
    loss_rate: float
    avg_turns: float
    avg_team_damage: float
    avg_team_damage_taken: float
    avg_team_survival_rate: float
    avg_team_health_remaining_pct: float
    score_primary: float


@dataclass
class CampaignExperimentRow:
    lance_id: str
    roster: str
    pv_total: int
    tier: str
    mode: str
    stage_order: str
    screen_sims: int
    final_sims: int
    full_clear_rate: float
    avg_stages_cleared: float
    stage1_pass_rate: float
    stage2_pass_rate: float
    stage3_pass_rate: float
    most_common_elimination_stage: str
    score_primary: float


def _field(obj: Any, attr: str) -> Any:
    if hasattr(obj, attr):
        return getattr(obj, attr)
    if isinstance(obj, dict):
        return obj[attr]
    raise AttributeError(f"Object {type(obj).__name__} has no field '{attr}'")


def load_mechs(csv_path: str = 'battlemechs_sim_ready.csv') -> pd.DataFrame:
    return pd.read_csv(csv_path)


def find_mech(df: pd.DataFrame, name: str) -> SimUnit:
    name = str(name).strip()

    # 1) Exact full-name match first
    exact = df[df["name"].astype(str).str.strip().str.casefold() == name.casefold()]
    if not exact.empty:
        return SimUnit.from_row(exact.iloc[0])

    # 2) Optional fallback: exact class_name + variant parse
    parts = name.rsplit(" ", 1)
    if len(parts) == 2:
        class_name, variant = parts[0].strip(), parts[1].strip()
        pair_match = df[
            (df["class_name"].astype(str).str.strip().str.casefold() == class_name.casefold()) &
            (df["variant"].astype(str).str.strip().str.casefold() == variant.casefold())
        ]
        if not pair_match.empty:
            return SimUnit.from_row(pair_match.iloc[0])

    # 3) Last-resort partial match only if unique
    partial = df[df["name"].astype(str).str.contains(re.escape(name), case=False, na=False)]
    if len(partial) == 1:
        return SimUnit.from_row(partial.iloc[0])

    if len(partial) > 1:
        raise ValueError(
            f"Ambiguous mech lookup for '{name}': "
            f"{partial['name'].head(10).tolist()}"
        )

    raise ValueError(f"No mech found matching '{name}'")


def select_tier(units: Sequence[Any]) -> str:
    total_pv = sum(int(_field(u, 'bf_point_value')) for u in units)
    if total_pv <= 133:
        return 'T1'
    if total_pv <= 166:
        return 'T2'
    return 'T3'


def tier_bounds(tier: str) -> tuple[int, int]:
    tier = tier.upper()
    if tier == 'T1':
        return 0, 133
    if tier == 'T2':
        return 134, 166
    if tier == 'T3':
        return 167, 200
    raise ValueError(f'Unknown tier: {tier}')


def build_clan_star(df: pd.DataFrame, star_name: str, tier: str) -> List[SimUnit]:
    if star_name not in CLAN_STARS:
        raise ValueError(f'Unknown Clan star: {star_name}')
    return [find_mech(df, mech_name) for mech_name in CLAN_STARS[star_name][tier]]


def canonical_roster(units: Sequence[Any]) -> List[str]:
    return sorted(_field(u, 'name') for u in units)


def roster_string(units: Sequence[Any]) -> str:
    return ' | '.join(canonical_roster(units))


def lance_id(units: Sequence[Any]) -> str:
    return '::'.join(canonical_roster(units))


def pv_total(units: Sequence[Any]) -> int:
    return int(sum(_field(u, 'bf_point_value') for u in units))


def rows_to_dataframe(rows: Sequence[Any]) -> pd.DataFrame:
    return pd.DataFrame([asdict(r) for r in rows])


def validate_lance_tier(units: Sequence[Any], expected_tier: str) -> None:
    expected_tier = expected_tier.upper()
    actual_tier = select_tier(units)
    total = pv_total(units)
    if actual_tier != expected_tier:
        raise ValueError(
            f"Lance tier mismatch: expected {expected_tier}, got {actual_tier}, "
            f"pv_total={total}, roster={roster_string(units)}"
        )


def build_manual_lance(df: pd.DataFrame, mech_names: Sequence[str]) -> List[SimUnit]:
    return [find_mech(df, name) for name in mech_names]


def sample_is_lance(
    df: pd.DataFrame,
    max_points: int = 200,
    lance_size: int = 4,
    allow_duplicates: bool = False,
    seed: Optional[int] = None,
    max_attempts: int = 1000,
) -> List[SimUnit]:
    rng = random.Random(seed)
    pool = df[df['technology'] == 'Inner Sphere'].copy()
    rows = list(pool.to_dict('records'))
    if not rows:
        raise ValueError('No Inner Sphere units available in dataframe.')

    for _ in range(max_attempts):
        chosen: List[Dict[str, Any]] = []
        budget = max_points
        chosen_names = set()

        for _slot in range(lance_size):
            candidates = [
                row for row in rows
                if int(row['bf_point_value']) <= budget
                and (allow_duplicates or row['name'] not in chosen_names)
            ]
            if not candidates:
                break
            pick = rng.choice(candidates)
            chosen.append(pick)
            chosen_names.add(pick['name'])
            budget -= int(pick['bf_point_value'])

        if len(chosen) == lance_size:
            return [SimUnit.from_row(pd.Series(row)) for row in chosen]

    raise ValueError('Unable to sample a valid IS lance under the PV cap.')


def sample_is_lance_for_tier(
    df: pd.DataFrame,
    tier: str,
    lance_size: int = 4,
    allow_duplicates: bool = False,
    seed: Optional[int] = None,
    max_attempts: int = 5000,
) -> List[SimUnit]:
    expected_tier = tier.upper()
    min_pv, max_pv = tier_bounds(expected_tier)
    rng = random.Random(seed)
    pool = df[df['technology'] == 'Inner Sphere'].copy()
    rows = list(pool.to_dict('records'))

    if not rows:
        raise ValueError('No Inner Sphere units available in dataframe.')

    for _ in range(max_attempts):
        chosen: List[Dict[str, Any]] = []
        chosen_names = set()
        running_pv = 0

        for _slot in range(lance_size):
            candidates = []
            for row in rows:
                name = row['name']
                pv = int(row['bf_point_value'])
                if not allow_duplicates and name in chosen_names:
                    continue
                if running_pv + pv > max_pv:
                    continue
                candidates.append(row)

            if not candidates:
                break

            pick = rng.choice(candidates)
            chosen.append(pick)
            chosen_names.add(pick['name'])
            running_pv += int(pick['bf_point_value'])

        if len(chosen) != lance_size:
            continue

        if min_pv <= running_pv <= max_pv:
            lance = [SimUnit.from_row(pd.Series(row)) for row in chosen]
            validate_lance_tier(lance, expected_tier)
            return lance

    raise ValueError(f'Unable to sample a valid IS lance for tier {tier}.')


def generate_candidate_lances(
    df: pd.DataFrame,
    n_candidates: int,
    max_points: int = 200,
    lance_size: int = 4,
    allow_duplicates: bool = False,
    seed: Optional[int] = None,
) -> List[List[SimUnit]]:
    rng = random.Random(seed)
    seen = set()
    out: List[List[SimUnit]] = []

    while len(out) < n_candidates:
        lance = sample_is_lance(
            df=df,
            max_points=max_points,
            lance_size=lance_size,
            allow_duplicates=allow_duplicates,
            seed=rng.randint(0, 2**31 - 1),
        )
        key = lance_id(lance)
        if key in seen:
            continue
        seen.add(key)
        out.append(lance)

    return out


def generate_lances_for_tier(
    df: pd.DataFrame,
    tier: str,
    n_lances: int = 100,
    allow_duplicates: bool = False,
    seed: Optional[int] = None,
) -> List[List[SimUnit]]:
    expected_tier = tier.upper()
    rng = random.Random(seed)
    seen = set()
    out: List[List[SimUnit]] = []

    while len(out) < n_lances:
        lance = sample_is_lance_for_tier(
            df=df,
            tier=expected_tier,
            allow_duplicates=allow_duplicates,
            seed=rng.randint(0, 2**31 - 1),
        )

        validate_lance_tier(lance, expected_tier)

        key = lance_id(lance)
        if key in seen:
            continue
        seen.add(key)
        out.append(lance)

    return out


def lances_to_csv_rows(
    lances: Sequence[Sequence[Any]],
    source_tag: str = 'generated'
) -> List[Dict[str, Any]]:
    rows = []
    for lance in lances:
        mech_names = canonical_roster(lance)
        rows.append({
            'source_tag': source_tag,
            'tier': select_tier(lance),
            'lance_id': lance_id(lance),
            'roster': ' | '.join(mech_names),
            'pv_total': pv_total(lance),
            'mech_1': mech_names[0],
            'mech_2': mech_names[1],
            'mech_3': mech_names[2],
            'mech_4': mech_names[3],
        })
    return rows


def write_lances_csv(
    lances: Sequence[Sequence[Any]],
    csv_path: str,
    source_tag: str = 'generated',
    expected_tier: Optional[str] = None
) -> pd.DataFrame:
    if expected_tier is not None:
        for lance in lances:
            validate_lance_tier(lance, expected_tier)

    df_out = pd.DataFrame(lances_to_csv_rows(lances, source_tag=source_tag))

    if expected_tier is not None and not df_out.empty:
        bad_rows = df_out[df_out['tier'].str.upper() != expected_tier.upper()]
        if not bad_rows.empty:
            raise ValueError(
                f'CSV write validation failed: found rows outside expected tier {expected_tier}'
            )

    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(csv_path, index=False)
    return df_out


def load_lances_from_csv(
    mech_df: pd.DataFrame,
    csv_path: str,
    expected_tier: Optional[str] = None
) -> List[List[SimUnit]]:
    lance_df = pd.read_csv(csv_path)
    required_cols = ['mech_1', 'mech_2', 'mech_3', 'mech_4']
    missing = [c for c in required_cols if c not in lance_df.columns]
    if missing:
        raise ValueError(f'Lance CSV missing required columns: {missing}')

    out: List[List[SimUnit]] = []
    for idx, row in lance_df.iterrows():
        mech_names = [str(row[c]).strip() for c in required_cols]
        lance = build_manual_lance(mech_df, mech_names)

        row_expected_tier = expected_tier
        if row_expected_tier is None and 'tier' in lance_df.columns and pd.notna(row.get('tier')):
            row_expected_tier = str(row['tier']).strip()

        if row_expected_tier:
            try:
                validate_lance_tier(lance, row_expected_tier)
            except ValueError as exc:
                raise ValueError(f'CSV row {idx + 1} failed tier validation: {exc}') from exc

        out.append(lance)

    return out


def summarize_matchup_results(
    units: Sequence[Any],
    target_op: str,
    tier: str,
    results: Any,
    screen_sims: int,
    final_sims: int,
) -> StarExperimentRow:
    total_damage = 0.0
    total_damage_taken = 0.0
    total_survival_rate = 0.0
    total_health_remaining_pct = 0.0
    n_runs = max(int(getattr(results, 'n_simulations')), 1)

    for run in getattr(results, 'runs'):
        side_a_units = [ur for ur in getattr(run, 'unit_results') if getattr(ur, 'side') == 'A']
        total_damage += sum(getattr(ur, 'damage_dealt') for ur in side_a_units)
        total_damage_taken += sum(getattr(ur, 'damage_taken') for ur in side_a_units)
        total_survival_rate += sum(1 for ur in side_a_units if getattr(ur, 'survived')) / max(len(side_a_units), 1)
        total_health_remaining_pct += (
            sum(getattr(ur, 'health_remaining') for ur in side_a_units)
            / max(sum(getattr(ur, 'health_max') for ur in side_a_units), 1)
        )

    win_rate = float(results.win_rate_a())
    draw_rate = float(results.draw_rate())

    return StarExperimentRow(
        lance_id=lance_id(units),
        roster=roster_string(units),
        pv_total=pv_total(units),
        tier=tier,
        mode='star',
        target_op=target_op,
        screen_sims=screen_sims,
        final_sims=final_sims,
        win_rate=win_rate,
        draw_rate=draw_rate,
        loss_rate=1.0 - win_rate - draw_rate,
        avg_turns=float(results.avg_turns()),
        avg_team_damage=total_damage / n_runs,
        avg_team_damage_taken=total_damage_taken / n_runs,
        avg_team_survival_rate=total_survival_rate / n_runs,
        avg_team_health_remaining_pct=total_health_remaining_pct / n_runs,
        score_primary=win_rate,
    )


def summarize_campaign_results(
    units: Sequence[Any],
    tier: str,
    results: Any,
    screen_sims: int,
    final_sims: int,
) -> CampaignExperimentRow:
    stage_stats = list(results.stage_stats())
    stage_names = list(getattr(results, 'stage_names'))
    elimination_breakdown = dict(results.elimination_breakdown())
    avg_stages_cleared = (
        sum(getattr(run, 'stages_won') for run in getattr(results, 'runs'))
        / max(int(getattr(results, 'n_simulations')), 1)
    )

    most_common_elimination_stage = 'FULL CLEAR'
    if elimination_breakdown:
        most_common_elimination_stage = max(
            elimination_breakdown.items(),
            key=lambda item: item[1],
        )[0]

    return CampaignExperimentRow(
        lance_id=lance_id(units),
        roster=roster_string(units),
        pv_total=pv_total(units),
        tier=tier,
        mode='campaign',
        stage_order=' -> '.join(stage_names),
        screen_sims=screen_sims,
        final_sims=final_sims,
        full_clear_rate=float(results.full_clear_rate()),
        avg_stages_cleared=avg_stages_cleared,
        stage1_pass_rate=float(stage_stats[0]['cum_pct']) if len(stage_stats) > 0 else 0.0,
        stage2_pass_rate=float(stage_stats[1]['cum_pct']) if len(stage_stats) > 1 else 0.0,
        stage3_pass_rate=float(stage_stats[2]['cum_pct']) if len(stage_stats) > 2 else 0.0,
        most_common_elimination_stage=most_common_elimination_stage,
        score_primary=float(results.full_clear_rate()),
    )


def sort_star_rows(rows: Sequence[StarExperimentRow]) -> List[StarExperimentRow]:
    return sorted(
        rows,
        key=lambda r: (
            -r.score_primary,
            r.draw_rate,
            -r.avg_team_health_remaining_pct,
            r.avg_turns,
        ),
    )


def sort_campaign_rows(rows: Sequence[CampaignExperimentRow]) -> List[CampaignExperimentRow]:
    return sorted(
        rows,
        key=lambda r: (
            -r.score_primary,
            -r.avg_stages_cleared,
            -r.stage3_pass_rate,
        ),
    )


def run_star_experiment(
    df: pd.DataFrame,
    target_op: str,
    candidates: Sequence[Sequence[SimUnit]],
    screen_sims: int = 100,
    final_sims: int = 750,
    keep_top_n: int = 100,
) -> List[StarExperimentRow]:
    screen_rows: List[StarExperimentRow] = []
    for lance in candidates:
        tier = select_tier(lance)
        clan_force = build_clan_star(df, target_op, tier)
        results = run_matchup(
            force_a=list(lance),
            force_b=clan_force,
            force_a_name='IS Candidate',
            force_b_name=target_op,
            n_simulations=screen_sims,
            verbose=False,
            log=False,
        )
        screen_rows.append(summarize_matchup_results(lance, target_op, tier, results, screen_sims, 0))

    survivors = sort_star_rows(screen_rows)[:keep_top_n]
    survivor_ids = {row.lance_id for row in survivors}

    final_rows: List[StarExperimentRow] = []
    for lance in candidates:
        if lance_id(lance) not in survivor_ids:
            continue
        tier = select_tier(lance)
        clan_force = build_clan_star(df, target_op, tier)
        results = run_matchup(
            force_a=list(lance),
            force_b=clan_force,
            force_a_name='IS Candidate',
            force_b_name=target_op,
            n_simulations=final_sims,
            verbose=False,
            log=False,
        )
        final_rows.append(summarize_matchup_results(lance, target_op, tier, results, screen_sims, final_sims))

    return sort_star_rows(final_rows)


def run_campaign_experiment(
    df: pd.DataFrame,
    candidates: Sequence[Sequence[SimUnit]],
    stage_order: Optional[Sequence[str]] = None,
    screen_sims: int = 100,
    final_sims: int = 750,
    keep_top_n: int = 100,
) -> List[CampaignExperimentRow]:
    if stage_order is None:
        stage_order = list(CLAN_STARS.keys())

    screen_rows: List[CampaignExperimentRow] = []
    for lance in candidates:
        tier = select_tier(lance)
        clan_forces = {name: build_clan_star(df, name, tier) for name in stage_order}
        results = run_campaign(
            force_a=list(lance),
            clan_forces=clan_forces,
            stage_order=list(stage_order),
            force_a_name='IS Candidate',
            n_simulations=screen_sims,
            verbose=False,
            log=False,
        )
        screen_rows.append(summarize_campaign_results(lance, tier, results, screen_sims, 0))

    survivors = sort_campaign_rows(screen_rows)[:keep_top_n]
    survivor_ids = {row.lance_id for row in survivors}

    final_rows: List[CampaignExperimentRow] = []
    for lance in candidates:
        if lance_id(lance) not in survivor_ids:
            continue
        tier = select_tier(lance)
        clan_forces = {name: build_clan_star(df, name, tier) for name in stage_order}
        results = run_campaign(
            force_a=list(lance),
            clan_forces=clan_forces,
            stage_order=list(stage_order),
            force_a_name='IS Candidate',
            n_simulations=final_sims,
            verbose=False,
            log=False,
        )
        final_rows.append(summarize_campaign_results(lance, tier, results, screen_sims, final_sims))

    return sort_campaign_rows(final_rows)


def add_percentage_display_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    rate_columns = [
        'win_rate', 'draw_rate', 'loss_rate', 'avg_team_survival_rate',
        'avg_team_health_remaining_pct', 'full_clear_rate',
        'stage1_pass_rate', 'stage2_pass_rate', 'stage3_pass_rate',
        'score_primary'
    ]
    for col in rate_columns:
        if col in out.columns:
            out[f'{col}_pct'] = out[col] * 100.0
    return out


def export_rows(rows: Sequence[Any], csv_path: str) -> pd.DataFrame:
    df = rows_to_dataframe(rows)
    df = add_percentage_display_columns(df)
    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)
    return df


def console_preview(df: pd.DataFrame, max_rows: int = 10) -> pd.DataFrame:
    out = df.copy()

    preferred_pct_cols = [
        'win_rate_pct', 'draw_rate_pct', 'loss_rate_pct',
        'avg_team_survival_rate_pct', 'avg_team_health_remaining_pct_pct',
        'full_clear_rate_pct', 'stage1_pass_rate_pct',
        'stage2_pass_rate_pct', 'stage3_pass_rate_pct', 'score_primary_pct'
    ]

    hidden_decimal_cols = {
        'win_rate', 'draw_rate', 'loss_rate',
        'avg_team_survival_rate', 'avg_team_health_remaining_pct',
        'full_clear_rate', 'stage1_pass_rate', 'stage2_pass_rate',
        'stage3_pass_rate', 'score_primary'
    }

    keep_cols = [c for c in out.columns if c not in hidden_decimal_cols]
    ordered_cols = keep_cols + [c for c in preferred_pct_cols if c in out.columns]
    out = out[ordered_cols]

    for col in preferred_pct_cols:
        if col in out.columns:
            out[col] = out[col].map(lambda x: f'{x:.2f}%')

    float_cols = out.select_dtypes(include='float').columns
    for col in float_cols:
        out[col] = out[col].map(lambda x: f'{x:.3f}')

    return out.head(min(max_rows, len(out)))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='BattleTech experiment driver')
    parser.add_argument('--mode', choices=['star', 'campaign'], default='star')
    parser.add_argument('--csv', default='battlemechs_sim_ready.csv')
    parser.add_argument('--target-op', default='OP2_LONG_RANGE')
    parser.add_argument('--n-candidates', type=int, default=50)
    parser.add_argument('--screen-sims', type=int, default=100)
    parser.add_argument('--final-sims', type=int, default=750)
    parser.add_argument('--keep-top-n', type=int, default=10)
    parser.add_argument('--max-points', type=int, default=200)
    parser.add_argument('--allow-duplicates', action='store_true')
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--output', default='output/experiment_results.csv')
    parser.add_argument('--candidate-csv', default=None)
    parser.add_argument('--generate-tier-csv', default=None)
    parser.add_argument('--tier', choices=['T1', 'T2', 'T3'], default=None)
    parser.add_argument('--n-lances', type=int, default=100)
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    df = load_mechs(args.csv)

    if args.generate_tier_csv:
        if not args.tier:
            raise ValueError('--tier is required when using --generate-tier-csv')

        lances = generate_lances_for_tier(
            df=df,
            tier=args.tier,
            n_lances=args.n_lances,
            allow_duplicates=args.allow_duplicates,
            seed=args.seed,
        )

        out_df = write_lances_csv(
            lances,
            args.generate_tier_csv,
            source_tag=f'generated_{args.tier}',
            expected_tier=args.tier,
        )

        print(console_preview(out_df).to_string(index=False))
        print(f"\nWrote {len(out_df)} lances to {args.generate_tier_csv}")
        return

    if args.candidate_csv:
        candidates = load_lances_from_csv(
            df,
            args.candidate_csv,
            expected_tier=args.tier,
        )
    else:
        candidates = generate_candidate_lances(
            df=df,
            n_candidates=args.n_candidates,
            max_points=args.max_points,
            allow_duplicates=args.allow_duplicates,
            seed=args.seed,
        )

    if args.mode == 'star':
        rows = run_star_experiment(
            df=df,
            target_op=args.target_op,
            candidates=candidates,
            screen_sims=args.screen_sims,
            final_sims=args.final_sims,
            keep_top_n=args.keep_top_n,
        )
    else:
        rows = run_campaign_experiment(
            df=df,
            candidates=candidates,
            screen_sims=args.screen_sims,
            final_sims=args.final_sims,
            keep_top_n=args.keep_top_n,
        )

    out_df = export_rows(rows, args.output)
    if not out_df.empty:
        print(console_preview(out_df).to_string(index=False))
        print(f"\nWrote {len(out_df)} result rows to {args.output}")
    else:
        print('No rows generated.')


if __name__ == '__main__':
    main()