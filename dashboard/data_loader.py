"""Loads and aggregates data/master_dataset.csv for the results dashboard.

Never hardcodes a column list or an enum of expected values -- the master
dataset's schema has drifted before (see data/master_dataset_schema.csv vs.
the real CSV header) and will likely drift again as new topologies/environments
are added. Every filter option and column reference here is derived from
whatever is actually in the loaded DataFrame.
"""
from pathlib import Path

import pandas as pd

DATASET_PATH = Path(__file__).resolve().parent.parent / "data" / "master_dataset.csv"

FILTERABLE_COLUMNS = ["fault_type", "window_type", "topology", "environment", "mode"]


def load_data(path: Path = DATASET_PATH) -> pd.DataFrame:
    return pd.read_csv(path)


def get_filter_options(df: pd.DataFrame) -> dict:
    """Distinct values actually present, for building filter dropdowns dynamically."""
    return {
        col: sorted(df[col].dropna().unique().tolist())
        for col in FILTERABLE_COLUMNS
        if col in df.columns
    }


def apply_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    """filters: {column: value_or_empty}. Empty/None means 'all'."""
    for col, val in filters.items():
        if val and col in df.columns:
            df = df[df[col] == val]
    return df


def compute_summary_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Reproduces figures/summary_stats.csv: per (fault_type, window_type),
    the blast_radius distribution plus the % of runs where the breaker tripped
    (blast_radius > 0).
    """
    grouped = df.groupby(["fault_type", "window_type"])["blast_radius"]
    stats = grouped.agg(n="count", median="median", mean="mean", std="std", min="min", max="max").reset_index()
    trip_rate = (
        df.groupby(["fault_type", "window_type"])["blast_radius"]
        .apply(lambda s: (s > 0).mean() * 100)
        .reset_index(name="trip_rate_pct")
    )
    return stats.merge(trip_rate, on=["fault_type", "window_type"])


def blast_pivot(df: pd.DataFrame, agg: str) -> pd.DataFrame:
    """fig1: fault_type (rows) x window_type (cols), agg='median' or 'mean'."""
    return df.pivot_table(index="fault_type", columns="window_type", values="blast_radius", aggfunc=agg)


def trip_rate_pivot(df: pd.DataFrame) -> pd.DataFrame:
    """fig2: % of runs where the breaker tripped, fault_type x window_type."""
    return df.pivot_table(
        index="fault_type",
        columns="window_type",
        values="blast_radius",
        aggfunc=lambda s: (s > 0).mean() * 100,
    )


def count_based_blast(df: pd.DataFrame) -> pd.DataFrame:
    """fig3 input: COUNT_BASED rows only, blast_radius grouped by fault_type."""
    return df[df["window_type"] == "COUNT_BASED"][["fault_type", "blast_radius"]]
