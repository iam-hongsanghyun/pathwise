"""Generic imputation of missing numeric values.

Generalises the legacy shipping ``estimate_missing_tank_to_wake_by_distance_ratio``:
fill a missing target column from a per-group median of the
``target / driver`` ratio, falling back to the overall median ratio. The
imputed rows are reported so the caller can flag them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pathwise.logger import get_logger

logger = get_logger(__name__)


def impute_by_group_ratio(
    df: pd.DataFrame,
    target: str,
    driver: str,
    group_by: str,
) -> tuple[pd.DataFrame, list[str]]:
    r"""Fill missing ``target`` from a per-group median ``target/driver`` ratio.

    Algorithm:
        For each group ``g`` with at least one complete row::

            ratio_g = median(target_i / driver_i)   over complete rows in g

        A missing ``target`` is imputed as ``ratio_g * driver``. Groups with no
        complete row use the overall median ratio.

        ASCII::

            target_hat = median_ratio(group) * driver

    Args:
        df: Input frame (not mutated).
        target: Column to fill.
        driver: Predictor column (must be present and positive where used).
        group_by: Grouping column for the per-group ratio.

    Returns:
        ``(filled_df, imputed_index_labels)`` — a copy of ``df`` with ``target``
        filled where it was missing, and the string index labels of imputed rows.
    """
    out = df.copy()
    if target not in out.columns or driver not in out.columns:
        return out, []

    complete = out[out[target].notna() & out[driver].notna() & (out[driver] != 0)]
    overall_ratio = (
        float((complete[target] / complete[driver]).median()) if not complete.empty else np.nan
    )
    group_ratio: dict[object, float] = {}
    if group_by in out.columns:
        for gkey, sub in complete.groupby(group_by):
            group_ratio[gkey] = float((sub[target] / sub[driver]).median())

    imputed: list[str] = []
    missing_mask = out[target].isna()
    for idx in out.index[missing_mask]:
        raw_driver = out.at[idx, driver]
        if pd.isna(raw_driver):
            continue
        driver_val = float(raw_driver)  # type: ignore[arg-type]
        key: object = out.at[idx, group_by] if group_by in out.columns else None
        ratio = group_ratio.get(key, overall_ratio)
        if np.isnan(ratio):
            continue
        out.at[idx, target] = ratio * driver_val
        imputed.append(str(idx))

    if imputed:
        logger.warning("imputed %d missing '%s' values via %s ratio", len(imputed), target, driver)
    return out, imputed
