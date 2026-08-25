"""
backtest_props.py — offline evaluation of player-prop projection models.

Answers one question: does adjusting a player's recent-form baseline by how
soft/tough the opposing defence is against their position make the projection
*closer to what actually happened*?

Everything is walk-forward — for a given week W we only ever use data from
weeks < W, both for the player's baseline and for the defence's allowed rates.
No sportsbook lines are needed: a projection that tracks reality more closely
is a projection that beats any line more often.

Usage:
    python backtest_props.py                 # last completed season
    python backtest_props.py --season 2024
    python backtest_props.py --season 2024 --start-week 5
"""

import argparse

import numpy as np
import pandas as pd
import nflreadpy as nfl

# stat → positions worth projecting, and a floor to drop fringe/noise players
MARKETS = {
    "passing_yards":   {"positions": ("QB",),          "min_baseline": 100.0},
    "rushing_yards":   {"positions": ("RB",),          "min_baseline": 20.0},
    "receiving_yards": {"positions": ("WR", "TE"),     "min_baseline": 20.0},
    "receptions":      {"positions": ("WR", "TE", "RB"), "min_baseline": 2.0},
    "carries":         {"positions": ("RB",),          "min_baseline": 5.0},
}

DAMPINGS = (0.0, 0.25, 0.5, 0.75, 1.0)  # 0.0 == today's production model
FACTOR_CLIP = (0.65, 1.55)              # keep one lopsided matchup from dominating
ROLL_WINDOW = 5
ROLL_MIN = 3


def load_season(season: int) -> pd.DataFrame:
    cols = ["season_type", "season", "week", "player_id", "player_display_name",
            "position", "team", "opponent_team",
            "passing_yards", "rushing_yards", "receiving_yards", "receptions", "carries"]
    pl = nfl.load_player_stats([season])
    df = pl.select([c for c in cols if c in pl.columns]).to_pandas()
    df = df[df["season_type"] == "REG"]
    return df.dropna(subset=["opponent_team", "position"])


def defence_priors(df: pd.DataFrame, stat: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Per (defence, position, week): mean of that stat they allowed in all *earlier*
    weeks, plus the league-wide mean allowed in all earlier weeks.
    """
    weekly = (df.groupby(["opponent_team", "week", "position"])[stat]
                .sum().reset_index()
                .rename(columns={"opponent_team": "def_team"})
                .sort_values("week"))

    weekly["def_prior"] = (weekly.groupby(["def_team", "position"])[stat]
                                 .transform(lambda s: s.expanding().mean().shift(1)))

    league = (weekly.groupby(["position", "week"])[stat].mean().reset_index()
                    .sort_values("week"))
    league["league_prior"] = (league.groupby("position")[stat]
                                    .transform(lambda s: s.expanding().mean().shift(1)))

    return weekly[["def_team", "position", "week", "def_prior"]], league[["position", "week", "league_prior"]]


def build_samples(df: pd.DataFrame, stat: str, positions: tuple, min_baseline: float,
                  start_week: int) -> pd.DataFrame:
    p = df[df["position"].isin(positions)].sort_values(["player_id", "week"]).copy()

    # Baseline = mean of the player's previous games (never the current one)
    p["baseline"] = (p.groupby("player_id")[stat]
                      .transform(lambda s: s.shift(1).rolling(ROLL_WINDOW, min_periods=ROLL_MIN).mean()))

    def_prior, league_prior = defence_priors(df, stat)
    p = p.merge(def_prior, left_on=["opponent_team", "position", "week"],
                right_on=["def_team", "position", "week"], how="left")
    p = p.merge(league_prior, on=["position", "week"], how="left")

    p = p[(p["week"] >= start_week) & p["baseline"].notna()
          & p["def_prior"].notna() & p["league_prior"].notna()
          & (p["league_prior"] > 0) & (p["baseline"] >= min_baseline)]

    p["factor"] = (p["def_prior"] / p["league_prior"]).clip(*FACTOR_CLIP)
    p["actual"] = p[stat]
    return p[["player_display_name", "position", "week", "opponent_team",
              "baseline", "factor", "actual"]]


def evaluate(samples: pd.DataFrame) -> dict:
    base = samples["baseline"].to_numpy()
    actual = samples["actual"].to_numpy()
    factor = samples["factor"].to_numpy()
    residual = actual - base            # how much they beat their own recent form
    signal = base * (factor - 1.0)      # how much defence says to move them

    out = {"n": len(samples), "by_damping": {}}
    # Does the defence signal point the same way the player actually moved?
    if np.std(signal) > 0 and np.std(residual) > 0:
        out["corr_signal_residual"] = float(np.corrcoef(signal, residual)[0, 1])
        nz = signal != 0
        out["sign_agreement"] = float(np.mean(np.sign(signal[nz]) == np.sign(residual[nz]))) if nz.any() else float("nan")
    else:
        out["corr_signal_residual"] = float("nan")
        out["sign_agreement"] = float("nan")

    for d in DAMPINGS:
        proj = base * (1.0 + d * (factor - 1.0))
        err = proj - actual
        out["by_damping"][d] = {
            "mae": float(np.mean(np.abs(err))),
            "rmse": float(np.sqrt(np.mean(err ** 2))),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2025)
    ap.add_argument("--start-week", type=int, default=6,
                    help="first week to score (needs prior weeks to build baselines)")
    args = ap.parse_args()

    print(f"Loading {args.season} player stats…")
    df = load_season(args.season)
    print(f"  {len(df)} player-weeks, weeks {df['week'].min()}–{df['week'].max()}\n")

    summary = {}
    for stat, cfg in MARKETS.items():
        samples = build_samples(df, stat, cfg["positions"], cfg["min_baseline"], args.start_week)
        if samples.empty:
            print(f"{stat}: no samples\n")
            continue
        res = evaluate(samples)
        summary[stat] = res

        base_mae = res["by_damping"][0.0]["mae"]
        print(f"── {stat}  ({'/'.join(cfg['positions'])}, n={res['n']})")
        print(f"   corr(defence signal, actual over/under-performance) = {res['corr_signal_residual']:+.4f}")
        print(f"   sign agreement                                      = {res['sign_agreement']:.3f}")
        print(f"   {'damping':>8} {'MAE':>9} {'vs base':>9} {'RMSE':>9}")
        for d in DAMPINGS:
            m = res["by_damping"][d]
            delta = (m["mae"] - base_mae) / base_mae * 100
            tag = "  <- current" if d == 0.0 else ""
            print(f"   {d:>8.2f} {m['mae']:>9.3f} {delta:>+8.2f}% {m['rmse']:>9.3f}{tag}")
        print()

    print("=" * 64)
    print("Best damping per market (lowest MAE):")
    for stat, res in summary.items():
        best = min(DAMPINGS, key=lambda d: res["by_damping"][d]["mae"])
        base_mae = res["by_damping"][0.0]["mae"]
        gain = (res["by_damping"][best]["mae"] - base_mae) / base_mae * 100
        verdict = "defence helps" if best > 0 and gain < 0 else "no gain from defence"
        print(f"  {stat:18s} damping={best:.2f}  MAE {gain:+.2f}%   {verdict}")


if __name__ == "__main__":
    main()
