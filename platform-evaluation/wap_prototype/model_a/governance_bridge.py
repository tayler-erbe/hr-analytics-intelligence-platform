"""Import (not copy) the succession_models governance patterns: suppression, the export gate, the restricted
writer and the approval record. succession_models is a flat package whose modules do `from config import ...`,
so its config.py is loaded under the module name `config` for the duration of the import and restored after.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pandas as pd

from wap_prototype.model_a import config as C


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _import_succession():
    saved = sys.modules.get("config")
    try:
        succ_config = _load("config", C.SUCCESSION_DIR / "config.py")
        governance = _load("succession_models_governance", C.SUCCESSION_DIR / "governance.py")
    finally:
        if saved is not None:
            sys.modules["config"] = saved
        else:
            sys.modules.pop("config", None)
    return succ_config, governance


succ_config, governance = _import_succession()

# re-exported, unchanged
suppress = governance.suppress                    # primary + complementary suppression within one parent group
check_exportable = governance.check_exportable    # refuses identifier / protected columns and unsuppressed n < k
ExportBlocked = governance.ExportBlocked
write_restricted = governance.write_restricted    # writes the README_RESTRICTED.txt banner next to the file
approval_ok = succ_config.approval_ok
REQUIRED_SIGNOFFS = succ_config.REQUIRED_SIGNOFFS


def data_is_synthetic(pack_manifest: Path) -> bool:
    """True when the Phase 1 input pack's manifest says synthetic (the sample pack does)."""
    if not pack_manifest.exists():
        return False
    try:
        return json.loads(pack_manifest.read_text()).get("synthetic") is True
    except json.JSONDecodeError:
        return False


def person_level_gate(pack_manifest: Path, approval_file: Path = C.APPROVAL_FILE) -> tuple[bool, str]:
    """Protocol 6.3, the succession_models gate reused with the WAP environment variable: person-level Model A
    scores are written only when WAP_ENABLE_PERSON_LEVEL=1 AND (the input is the synthetic fixture OR
    governance/approval.json carries the Counsel, OAE and IHR sign-offs)."""
    if os.environ.get(C.PERSON_LEVEL_ENV) != "1":
        return False, f"person-level scores disabled (default; set {C.PERSON_LEVEL_ENV}=1 only after governance approval)"
    if data_is_synthetic(pack_manifest):
        return True, "enabled on SYNTHETIC data for audit demonstration only"
    ok, why = approval_ok(approval_file)
    return ok, (why if not ok else "enabled under recorded governance approval")


def suppress_multi(df: pd.DataFrame, n_col: str, value_cols: list[str], groupings: list[list[str]],
                   k: int = C.K_MIN) -> pd.DataFrame:
    """governance.suppress applied over several parent groupings to a fixed point.

    Primary rule: n < k. Complementary rule (identical to governance.suppress): when a parent group has exactly
    one suppressed cell and at least one published cell, the smallest published cell is suppressed too, so the
    group total cannot reveal it. With more than one grouping a complementary suppression in one grouping can
    leave a lone suppressed cell in another, so the rule is iterated until nothing changes. Suppressed rows keep
    their keys, carry `suppressed = True` and null measures; `suppression_reason` says why.
    """
    out = df.copy().reset_index(drop=True)
    n = out[n_col].astype(float)
    sup = n < k
    reason = pd.Series(["primary" if s else "" for s in sup], index=out.index, dtype=object)
    changed = True
    while changed:
        changed = False
        for keys in groupings:
            for _, idx in out.groupby(keys, dropna=False).groups.items():
                s = sup.loc[idx]
                if s.sum() == 1 and (~s).sum() >= 1:
                    j = n.loc[idx][~s].idxmin()
                    sup.loc[j] = True
                    reason.loc[j] = "complementary"
                    changed = True
    out["suppressed"] = sup.astype(bool)
    out["suppression_reason"] = reason
    cols = [c for c in value_cols if c in out.columns]
    for c in cols:
        out[c] = out[c].astype(object).where(~out["suppressed"], None)
    return out
