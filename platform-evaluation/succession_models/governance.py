"""Small-cell suppression and the export gate.

Everything that may leave the approved machine goes through `export_table`, which refuses
identifier or protected-attribute columns and any unsuppressed cell below K_MIN. Position-level
and person-level outputs are written by `write_restricted` to restricted/ and never exported.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from config import FORBIDDEN_EXPORT_COLS, K_MIN


class ExportBlocked(RuntimeError):
    pass


def suppress(df: pd.DataFrame, n_col: str, value_cols: list[str], group_col: str | None = None,
             k: int = K_MIN) -> pd.DataFrame:
    """Primary suppression (n < k) plus complementary suppression within `group_col`.

    Complementary rule: if a group has exactly one primarily suppressed cell and other published cells,
    the next-smallest cell in that group is also suppressed, so the suppressed value cannot be recovered
    by subtracting published cells from a published group total.
    """
    out = df.copy()
    out["suppressed"] = out[n_col].astype(float) < k
    if group_col is not None:
        for _, idx in out.groupby(group_col).groups.items():
            sub = out.loc[idx]
            if sub["suppressed"].sum() == 1 and (~sub["suppressed"]).sum() >= 1:
                j = sub.loc[~sub["suppressed"], n_col].astype(float).idxmin()
                out.loc[j, "suppressed"] = True
    cols = [c for c in value_cols if c in out.columns] + [n_col]
    out[cols] = out[cols].astype(float)
    out.loc[out["suppressed"], cols] = np.nan
    return out


def check_exportable(df: pd.DataFrame, n_col: str, k: int = K_MIN) -> None:
    bad = [c for c in df.columns if c.lower() in FORBIDDEN_EXPORT_COLS or "pers_id" in c.lower() or "posn" in c.lower()]
    if bad:
        raise ExportBlocked(f"identifier / protected columns may not be exported: {bad}")
    if n_col not in df.columns:
        raise ExportBlocked(f"export tables must carry a count column ({n_col!r}) for the k>={k} check")
    n = pd.to_numeric(df[n_col], errors="coerce")
    small = n.notna() & (n < k)
    if small.any():
        raise ExportBlocked(f"{int(small.sum())} unsuppressed cells with {n_col} < {k}")


def export_table(df: pd.DataFrame, name: str, export_dir: Path, n_col: str, k: int = K_MIN) -> Path:
    check_exportable(df, n_col, k)
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / f"{name}.csv"
    df.to_csv(path, index=False, float_format="%.4f")
    man = export_dir / "export_manifest.json"
    m = json.loads(man.read_text()) if man.exists() else {}
    m[name] = {"rows": int(len(df)), "count_column": n_col, "k_min": k,
               "suppressed_rows": int(df.get("suppressed", pd.Series(dtype=bool)).fillna(False).sum())}
    man.write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    return path


def write_restricted(df: pd.DataFrame, name: str, restricted_dir: Path) -> Path:
    restricted_dir = Path(restricted_dir)
    restricted_dir.mkdir(parents=True, exist_ok=True)
    (restricted_dir / "README_RESTRICTED.txt").write_text(
        "RESTRICTED. Position- or person-level model output. Stays on the approved machine, access limited to\n"
        "named HR planning staff. Never used as the basis for an employment decision about an incumbent.\n"
        "Never copied to the export/ folder, a dashboard, e-mail, or a cloud service.\n")
    path = restricted_dir / f"{name}.parquet"
    df.to_parquet(path, index=False)
    return path
