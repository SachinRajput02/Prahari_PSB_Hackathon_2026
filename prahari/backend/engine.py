"""
PRAHARI — CTQ engine.

Loads the trained LightGBM model and turns a live signal vector into:
  * a Continuous Trust Quotient (0-100)  = P(genuine) * 100, decayed by inactivity
  * SHAP reason codes  = per-feature attribution of why trust moved
  * a step-up decision = SILENT / SOFT / HARD given the action's trust threshold
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import joblib
import shap

HERE = Path(__file__).parent
_meta = json.loads((HERE / "features.json").read_text())
FEATURES = _meta["features"]
LABELS = _meta["labels"]

_model = joblib.load(HERE / "model.pkl")
_explainer = shap.TreeExplainer(_model)

# Per-action trust thresholds (sensitivity-graded). Higher = more trust required.
ACTIONS = {
    "balance":  {"label": "View balance",        "req": 35},
    "login":    {"label": "Login",               "req": 48},
    "benef":    {"label": "Add beneficiary",     "req": 66},
    "transfer": {"label": "High-value transfer", "req": 76},
    "recovery": {"label": "Account recovery",    "req": 86},
    "admin":    {"label": "Privileged admin",    "req": 84},
}

DEFAULTS = {f: 0 for f in FEATURES}
DEFAULTS.update({"behavioral_mismatch": 0.05, "device_age_days": 240})

# Deterministic high-risk policy ceilings. Real fraud systems pair an ML score
# with hard rules: certain signals cap how much trust is permissible regardless
# of context (e.g. a detected SIM-swap is a known account-takeover precursor).
# CTQ = min(ML score, every applicable ceiling).
POLICY = [
    ("sim_swap",          lambda s: bool(s.get("sim_swap")),                              42, "SIM-swap → trust ceiling"),
    ("impossible_travel", lambda s: bool(s.get("impossible_travel")),                     58, "Impossible travel → trust ceiling"),
    ("ip_bad",            lambda s: bool(s.get("ip_bad")),                                 52, "Known-bad network → trust ceiling"),
    ("recovery_attempts", lambda s: s.get("recovery_attempts", 0) >= 3,                    48, "Repeated recovery → trust ceiling"),
    ("new_device_hv",     lambda s: bool(s.get("new_device")) and s.get("amount_zscore", 0) > 1.5, 60, "New device + high value → trust ceiling"),
]


def apply_policy(signals: dict, ml_ctq: float):
    hits, ceil = [], 100.0
    for _, cond, cap, label in POLICY:
        if cond(signals):
            hits.append({"rule": label, "ceiling": cap})
            ceil = min(ceil, cap)
    return min(ml_ctq, ceil), hits


def _vector(signals: dict) -> pd.DataFrame:
    row = dict(DEFAULTS)
    row.update({k: v for k, v in signals.items() if k in FEATURES})
    return pd.DataFrame([row])[FEATURES]


def raw_trust(signals: dict) -> float:
    """P(genuine) * 100, before decay."""
    X = _vector(signals)
    p = float(_model.predict_proba(X)[:, 1][0])
    return p * 100.0


def decay_factor(idle_seconds: float) -> float:
    """Trust erodes with inactivity and must be re-earned. 0 = fresh, ->1 = stale."""
    if idle_seconds <= 8:
        return 0.0
    return float(min(1.0, (idle_seconds - 8) / 40.0))


def reason_codes(signals: dict, top: int = 6):
    """SHAP attribution toward the FRAUD outcome (i.e. what lowers trust)."""
    X = _vector(signals)
    sv = _explainer.shap_values(X)
    # LightGBM binary -> margin contribution toward positive (genuine) class.
    arr = sv[0] if isinstance(sv, list) else sv
    arr = np.asarray(arr)
    if arr.ndim == 3:        # (n, features, classes)
        contrib = arr[0, :, 1]
    elif arr.ndim == 2:
        contrib = arr[0]
    else:
        contrib = arr
    out = []
    for f, c in zip(FEATURES, contrib):
        # negative contribution to "genuine" margin == pushes toward fraud
        if c < -1e-4 and signals.get(f, DEFAULTS.get(f, 0)):
            out.append({"feature": f, "label": LABELS[f], "impact": round(float(-c), 3)})
    out.sort(key=lambda d: d["impact"], reverse=True)
    return out[:top]


def band(ctq: float):
    if ctq >= 70:
        return "trusted"
    if ctq >= 40:
        return "elevated"
    return "high_risk"


def decide(ctq: float, action: str):
    a = ACTIONS.get(action, ACTIONS["transfer"])
    margin = ctq - a["req"]
    if margin >= 0:
        kind, friction = "silent", "none"
        msg = f"Trust {ctq:.0f} ≥ threshold {a['req']} for “{a['label']}”. Access granted with no added friction."
    elif margin >= -20:
        kind, friction = "soft", "step_up_lite"
        msg = f"Trust {ctq:.0f} below threshold {a['req']}. Silent re-auth / device re-bind before “{a['label']}”."
    else:
        kind, friction = "hard", "strong_verification"
        msg = f"Trust {ctq:.0f} far below threshold {a['req']}. “{a['label']}” blocked pending OTP + biometric / liveness."
    return {"kind": kind, "friction": friction, "threshold": a["req"],
            "action_label": a["label"], "message": msg}


def score(signals: dict, action: str = "transfer", idle_seconds: float = 0.0):
    base = raw_trust(signals)
    capped, policy_hits = apply_policy(signals, base)
    d = decay_factor(idle_seconds)
    ctq = round(max(1.0, min(99.0, capped * (1 - d * 0.45))))
    return {
        "ctq": ctq,
        "ml_trust": round(base, 1),
        "policy_ceiling": round(capped, 1) if policy_hits else None,
        "policy_hits": policy_hits,
        "decay": round(d, 3),
        "band": band(ctq),
        "reasons": reason_codes(signals),
        "decision": decide(ctq, action),
    }
