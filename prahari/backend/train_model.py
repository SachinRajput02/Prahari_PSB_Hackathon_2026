"""
PRAHARI — CTQ model trainer.

Generates a synthetic, labelled dataset of banking sessions (genuine vs. fraud),
trains a LightGBM classifier, and persists it. The model's probability that a
session is *genuine* becomes the Continuous Trust Quotient (CTQ = P(genuine)*100).

Data is designed so every signal independently shifts fraud probability with
realistic overlap: some genuine users legitimately make large transfers or buy
new phones, and some fraud is deliberately low-and-slow. This keeps the model
honest (no perfect separation) and sensitive to each live signal.
"""
import json
import numpy as np
import pandas as pd
import lightgbm as lgb
from pathlib import Path
import joblib

HERE = Path(__file__).parent
RNG = np.random.default_rng(42)

FEATURES = [
    "new_device", "impossible_travel", "sim_swap", "odd_hour",
    "recovery_attempts", "behavioral_mismatch", "ip_bad", "ip_vpn",
    "device_age_days", "failed_auth_24h", "amount_zscore",
]

FEATURE_LABELS = {
    "new_device": "New / unrecognised device",
    "impossible_travel": "Impossible geo-velocity",
    "sim_swap": "SIM-swap detected",
    "odd_hour": "Odd-hour access",
    "recovery_attempts": "Rapid recovery attempts",
    "behavioral_mismatch": "Behavioural biometric mismatch",
    "ip_bad": "Known-bad network",
    "ip_vpn": "VPN / proxy network",
    "device_age_days": "Unfamiliar / young device",
    "failed_auth_24h": "Recent failed auth attempts",
    "amount_zscore": "Anomalous transaction value",
}


def _genuine(n):
    amt = RNG.exponential(0.45, n)
    big = RNG.random(n) < 0.09          # 9% legit large transfers
    amt = np.where(big, amt + RNG.exponential(1.6, n), amt)
    newdev = RNG.binomial(1, 0.12, n)
    return pd.DataFrame({
        "new_device": newdev,
        "impossible_travel": RNG.binomial(1, 0.004, n),
        "sim_swap": RNG.binomial(1, 0.003, n),
        "odd_hour": RNG.binomial(1, 0.16, n),
        "recovery_attempts": RNG.poisson(0.05, n).clip(0, 5),
        "behavioral_mismatch": RNG.beta(2, 20, n),
        "ip_bad": RNG.binomial(1, 0.004, n),
        "ip_vpn": RNG.binomial(1, 0.12, n),
        # new-device genuine users get a young device age; rest mature
        "device_age_days": np.where(newdev, RNG.exponential(12, n), RNG.exponential(240, n)).clip(0, 720),
        "failed_auth_24h": RNG.poisson(0.25, n).clip(0, 8),
        "amount_zscore": amt.clip(0, 5),
        "label": 1,
    })


def _fraud(n):
    amt = RNG.exponential(1.3, n) + 0.4
    low = RNG.random(n) < 0.22          # 22% low-and-slow (small probing txns)
    amt = np.where(low, RNG.exponential(0.4, n), amt)
    newdev = RNG.binomial(1, 0.62, n)
    return pd.DataFrame({
        "new_device": newdev,
        "impossible_travel": RNG.binomial(1, 0.36, n),
        "sim_swap": RNG.binomial(1, 0.30, n),
        "odd_hour": RNG.binomial(1, 0.50, n),
        "recovery_attempts": RNG.poisson(0.85, n).clip(0, 5),
        "behavioral_mismatch": RNG.beta(5, 5, n),
        "ip_bad": RNG.binomial(1, 0.38, n),
        "ip_vpn": RNG.binomial(1, 0.28, n),
        "device_age_days": np.where(newdev, RNG.exponential(6, n), RNG.exponential(60, n)).clip(0, 720),
        "failed_auth_24h": RNG.poisson(1.8, n).clip(0, 8),
        "amount_zscore": amt.clip(0, 5),
        "label": 0,
    })


def build_dataset(n_genuine=13000, n_fraud=7000):
    df = pd.concat([_genuine(n_genuine), _fraud(n_fraud)], ignore_index=True)
    flip = RNG.random(len(df)) < 0.015   # 2% label noise -> no perfect boundary
    df.loc[flip, "label"] = 1 - df.loc[flip, "label"]
    return df.sample(frac=1, random_state=7).reset_index(drop=True)


def train():
    df = build_dataset()
    X, y = df[FEATURES], df["label"]
    split = int(len(df) * 0.85)
    Xtr, Xte, ytr, yte = X[:split], X[split:], y[:split], y[split:]

    # Monotonic risk priors: every risk feature can only LOWER P(genuine);
    # device age can only RAISE it. Encodes domain knowledge, guarantees the
    # model responds sensibly to each signal, and resists spurious correlations.
    mono = {"new_device": -1, "impossible_travel": -1, "sim_swap": -1,
            "odd_hour": -1, "recovery_attempts": -1, "behavioral_mismatch": -1,
            "ip_bad": -1, "ip_vpn": -1, "device_age_days": 1,
            "failed_auth_24h": -1, "amount_zscore": -1}
    model = lgb.LGBMClassifier(
        n_estimators=350, learning_rate=0.045, num_leaves=24,
        subsample=0.85, colsample_bytree=0.85, min_child_samples=60,
        reg_lambda=1.0, random_state=42, n_jobs=2, verbose=-1,
        monotone_constraints=[mono[f] for f in FEATURES],
    )
    model.fit(Xtr, ytr)

    from sklearn.metrics import roc_auc_score, average_precision_score
    p = model.predict_proba(Xte)[:, 1]
    auc = roc_auc_score(yte, p)
    ap = average_precision_score(yte, p)

    joblib.dump(model, HERE / "model.pkl")
    (HERE / "features.json").write_text(json.dumps(
        {"features": FEATURES, "labels": FEATURE_LABELS}, indent=2))

    print(f"trained LightGBM  ROC-AUC={auc:.4f}  PR-AUC={ap:.4f}  n={len(df)}")
    return auc, ap


if __name__ == "__main__":
    train()
