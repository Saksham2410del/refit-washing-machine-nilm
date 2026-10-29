"""Part 3: estimate washing-machine power from the aggregate signal (cleaned REFIT, 1-minute).

Two evaluations on the same test months:
  chronological   - one model on all houses, each house split 70/15/15 by time
  leave-one-house - train on the other houses only, test on the unseen house

Usage: python src/train_disaggregation.py [--data-dir PATH]
"""
import argparse
from pathlib import Path

import lightgbm as lgb
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import (AGG_COLOR, DATA_DIR, FIG_DIR, HEATED_W, HOUSES, MAX_ISSUE_SHARE, ON_W, OTHER_COLOR,
                    OTHER_HEATERS, OUT_DIR, PRED_COLOR, TABLE_DIR, WM_COLOR, detect_cycles, frozen_mask,
                    load_clean_house, setup_plots, silent_mask, stuck_mask)

WINDOWS = [5, 15, 30, 60]
FEATURES = (["agg"] + [f"{stat}_{w}" for w in WINDOWS for stat in ["mean", "min", "max", "std"]]
            + ["diff_1", "diff_5", "hour"])
CUTS = [20, 50, 100, 200, 300]   # candidate floors for the model output, chosen on validation
OTHER_ON_W = 500                  # another heating appliance counts as "on" above this


def make_features(agg):
    """Features from the aggregate only. Every window looks backwards, never ahead."""
    feats = pd.DataFrame(index=agg.index)
    for w in WINDOWS:
        roll = agg.rolling(w, min_periods=1)
        feats[f"mean_{w}"] = roll.mean()
        feats[f"min_{w}"] = roll.min()
        feats[f"max_{w}"] = roll.max()
        feats[f"std_{w}"] = roll.std()
    feats["diff_1"] = agg.diff(1)    # step changes: heater switching on/off is a ~2 kW jump
    feats["diff_5"] = agg.diff(5)
    feats["hour"] = agg.index.hour
    return feats.astype("float32")


def load_house(house, data_dir):
    """1-minute data for one house with features, a usable flag and a 70/15/15 time split."""
    df = load_clean_house(house, data_dir, extra=OTHER_HEATERS.get(house))
    df["frozen"] = frozen_mask(df["agg"])
    df["agg"] = df["agg"].where(~df["frozen"])
    # a stuck or long-silent monitor gives no trustworthy label
    df["wm"] = df["wm"].where(~stuck_mask(df["wm"]) & ~silent_mask(df["wm"]))
    df = df.join(make_features(df["agg"]))
    # rows we train and score on: real (not frozen) readings, and not mostly flagged by Issues
    df["usable"] = df["agg"].notna() & df["wm"].notna() & (df["issues"] <= MAX_ISSUE_SHARE)

    times = df.index[df["usable"]]
    t_val = times[int(0.70 * len(times))]
    t_test = times[int(0.85 * len(times))]
    df["split"] = np.where(df.index < t_val, "train", np.where(df.index < t_test, "val", "test"))
    df["house"] = house
    return df


def scores(y, pred):
    """MAE overall and while the machine runs, on/off precision/recall/F1, and total-energy error."""
    y = np.asarray(y, dtype=float)
    pred = np.asarray(pred, dtype=float)
    true_on = y >= ON_W
    pred_on = pred >= ON_W
    tp = np.sum(true_on & pred_on)
    fp = np.sum(~true_on & pred_on)
    fn = np.sum(true_on & ~pred_on)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "mae_w": np.mean(np.abs(pred - y)),
        "mae_on_w": np.mean(np.abs(pred[true_on] - y[true_on])) if true_on.any() else np.nan,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "true_kwh": y.sum() / 60000,
        "pred_kwh": pred.sum() / 60000,
        "energy_error_pct": 100 * (pred.sum() - y.sum()) / y.sum() if y.sum() > 0 else np.nan,
    }


def postprocess(raw, cut):
    """Clip at 0 and set anything below the cut to 0; the machine is either running or it is not."""
    pred = np.clip(raw, 0, None)
    pred[pred < cut] = 0.0
    return pred


def fit_model(train, val):
    """LightGBM with early stopping on validation, then pick the output floor with the best validation F1."""
    model = lgb.LGBMRegressor(n_estimators=1000, learning_rate=0.05, num_leaves=63,
                              min_child_samples=100, random_state=42, verbose=-1)
    model.fit(train[FEATURES], train["wm"], eval_X=val[FEATURES], eval_y=val["wm"],
              callbacks=[lgb.early_stopping(50, verbose=False)])
    raw_val = model.predict(val[FEATURES])
    best_cut, best_f1 = CUTS[0], -1.0
    for cut in CUTS:
        f1 = scores(val["wm"], postprocess(raw_val, cut))["f1"]
        if f1 > best_f1:
            best_cut, best_f1 = cut, f1
    return model, best_cut


def hourly_profile(train, test, per_house):
    """Baseline: average washing-machine power for each hour of the day, from training rows only."""
    if per_house:
        profile = train.groupby(["house", "hour"])["wm"].mean()
        keys = pd.MultiIndex.from_arrays([test["house"], test["hour"]])
    else:
        profile = train.groupby("hour")["wm"].mean()
        keys = test["hour"]
    return profile.reindex(keys).fillna(0).to_numpy()


def score_table(setup, test, preds):
    rows = []
    for method, pred in preds.items():
        groups = [("all", np.ones(len(test), dtype=bool))]
        for h in HOUSES:
            groups.append((h, (test["house"] == h).to_numpy()))
        for house, m in groups:
            row = {"setup": setup, "house": house, "method": method}
            row.update(scores(test["wm"].to_numpy()[m], pred[m]))
            rows.append(row)
    return rows


def pick_test_cycle(df):
    """A test-period cycle with typical (median) energy, so the plot is not cherry-picked."""
    test = df[df["split"] == "test"]
    cycles = detect_cycles(test["wm"].where(test["usable"]))
    if cycles.empty:
        return None
    return cycles.iloc[(cycles["energy_kwh"] - cycles["energy_kwh"].median()).abs().to_numpy().argmin()]


def plot_actual_vs_pred(frames, path):
    fig, axes = plt.subplots(len(HOUSES), 1, figsize=(11, 2.8 * len(HOUSES)))
    for ax, h in zip(np.atleast_1d(axes), HOUSES):
        df = frames[h]
        cyc = pick_test_cycle(df)
        if cyc is None:
            ax.set_title(f"House {h}: no cycles in the test period")
            continue
        win = df.loc[cyc["start"] - pd.Timedelta(hours=1): cyc["end"] + pd.Timedelta(hours=1)]
        x = win.index.tz_localize(None)
        ax.plot(x, win["agg"], color=AGG_COLOR, lw=0.8, label="Aggregate (model input)")
        ax.plot(x, win["wm"], color=WM_COLOR, lw=1.4, label="Washing machine, measured")
        ax.plot(x, win["pred"], color=PRED_COLOR, lw=1.4, label="Washing machine, predicted")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax.set_ylabel("W")
        ax.set_title(f"House {h}, {cyc['start']:%a %d %b %Y} (test period, typical cycle)")
    np.atleast_1d(axes)[0].legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def plot_failure(frames, path):
    """The 6 test hours where the model invents the most washing-machine energy."""
    best = None
    for h in HOUSES:
        test = frames[h][frames[h]["split"] == "test"]
        wrong = test["pred"].where(test["wm"] < ON_W, 0).fillna(0)
        score = wrong.rolling(360).sum()
        if best is None or score.max() > best[0]:
            best = (score.max(), h, score.idxmax())
    _, h, end = best
    win = frames[h].loc[end - pd.Timedelta(minutes=359): end]
    x = win.index.tz_localize(None)

    heater_cols = list(OTHER_HEATERS.get(h, {}))
    other = win[heater_cols].sum().idxmax() if heater_cols else None
    other_kwh = win[other].sum() / 60000 if other else 0.0

    fig, ax = plt.subplots(figsize=(11, 3.8))
    ax.plot(x, win["agg"], color=AGG_COLOR, lw=0.8, label="Aggregate (model input)")
    if other and other_kwh > 0.05:
        ax.plot(x, win[other], color=OTHER_COLOR, lw=1.2, label=f"{other.replace('_', ' ').capitalize()}, measured")
    ax.plot(x, win["wm"], color=WM_COLOR, lw=1.4, label="Washing machine, measured")
    ax.plot(x, win["pred"], color=PRED_COLOR, lw=1.4, label="Washing machine, predicted")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.set_ylabel("W")
    ax.set_title(f"Failure case: House {h}, {x[0]:%a %d %b %Y} - predicted washing machine energy that is not there")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return h, win.index[0], other, other_kwh


def false_positive_report(frames):
    """How often a false 'on' minute coincides with another metered heating appliance running."""
    rows = []
    for h in HOUSES:
        df = frames[h]
        t = df[(df["split"] == "test") & df["usable"]]
        fp = (t["pred"] >= ON_W) & (t["wm"] < ON_W)
        heater_cols = list(OTHER_HEATERS.get(h, {}))
        other_on = (t[heater_cols] > OTHER_ON_W).any(axis=1) if heater_cols else pd.Series(False, index=t.index)
        rows.append({"house": h,
                     "false_on_minutes": int(fp.sum()),
                     "false_on_kwh": round(t.loc[fp, "pred"].sum() / 60000, 2),
                     "other_heater_on_during_false_on_pct": round(100 * other_on[fp].mean(), 1) if fp.any() else np.nan,
                     "other_heater_on_all_test_minutes_pct": round(100 * other_on.mean(), 1)})
    return pd.DataFrame(rows)


def cycle_recall(frames):
    """Share of real test cycles the model catches (half or more of the cycle's minutes predicted on)."""
    rows = []
    for h in HOUSES:
        test = frames[h][frames[h]["split"] == "test"]
        cycles = detect_cycles(test["wm"].where(test["usable"]))
        pred_on = (test["pred"] >= ON_W).to_numpy()
        for _, c in cycles.iterrows():
            s = test.index.get_loc(c["start"])
            e = test.index.get_loc(c["end"])
            share = pred_on[s:e + 1].mean()
            rows.append({"house": h, "start": c["start"], "heated": bool(c["peak_w"] >= HEATED_W),
                         "energy_kwh": round(c["energy_kwh"], 3), "share_predicted_on": round(share, 3),
                         "caught": bool(share >= 0.5)})
    per_cycle = pd.DataFrame(rows)
    summary = per_cycle.groupby(["house", "heated"])["caught"].agg(cycles="size", caught_pct="mean").reset_index()
    summary["caught_pct"] = (100 * summary["caught_pct"]).round(1)
    overall = per_cycle.groupby("heated")["caught"].agg(cycles="size", caught_pct="mean").reset_index()
    overall["caught_pct"] = (100 * overall["caught_pct"]).round(1)
    overall.insert(0, "house", "all")
    return per_cycle, pd.concat([summary, overall], ignore_index=True)


def plot_importance(model, path):
    gain = pd.Series(model.booster_.feature_importance("gain"), index=FEATURES)
    share = (100 * gain / gain.sum()).sort_values()
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.barh(share.index, share.to_numpy(), color=WM_COLOR)
    ax.set_xlabel("% of total split gain")
    ax.set_title("LightGBM feature importance (chronological model)")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return share.sort_values(ascending=False)


def main(data_dir):
    setup_plots()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    TABLE_DIR.mkdir(parents=True, exist_ok=True)

    frames = {}
    for house in HOUSES:
        print(f"Loading House {house}")
        frames[house] = load_house(house, data_dir)

    split_rows = []
    for house, df in frames.items():
        for part in ["train", "val", "test"]:
            rows = df[(df["split"] == part) & df["usable"]]
            split_rows.append({"house": house, "split": part,
                               "start": rows.index.min().strftime("%Y-%m-%d"),
                               "end": rows.index.max().strftime("%Y-%m-%d"),
                               "usable_minutes": len(rows),
                               "wm_on_pct": round(100 * (rows["wm"] >= ON_W).mean(), 2)})
    splits = pd.DataFrame(split_rows)
    pd.set_option("display.width", 200)
    print("\nPeriods used (70/15/15 by time within each house)")
    print(splits.to_string(index=False))

    table = pd.concat([df[df["usable"]].reset_index(names="time") for df in frames.values()], ignore_index=True)
    train = table[table["split"] == "train"]
    val = table[table["split"] == "val"]
    test = table[table["split"] == "test"]

    print(f"\nChronological model: {len(train):,} train rows, {len(val):,} val rows, {len(test):,} test rows")
    model, cut = fit_model(train, val)
    print(f"  best iteration {model.best_iteration_}, output floor {cut} W")
    chrono = {
        "always_off": np.zeros(len(test)),
        "hourly_profile": hourly_profile(train, test, per_house=True),
        "lightgbm": postprocess(model.predict(test[FEATURES]), cut),
    }

    loho = {"always_off": np.zeros(len(test)), "hourly_profile": np.zeros(len(test)), "lightgbm": np.zeros(len(test))}
    for h in HOUSES:
        m = (test["house"] == h).to_numpy()
        tr = train[train["house"] != h]
        va = val[val["house"] != h]
        model_h, cut_h = fit_model(tr, va)
        loho["hourly_profile"][m] = hourly_profile(tr, test[m], per_house=False)
        loho["lightgbm"][m] = postprocess(model_h.predict(test.loc[m, FEATURES]), cut_h)
        print(f"Leave-one-house-out, test House {h}: trained on houses {[x for x in HOUSES if x != h]}, "
              f"best iteration {model_h.best_iteration_}, output floor {cut_h} W")

    metrics = pd.DataFrame(score_table("chronological", test, chrono) + score_table("leave_one_house_out", test, loho))
    show = metrics.round({"mae_w": 1, "mae_on_w": 1, "precision": 3, "recall": 3, "f1": 3,
                          "true_kwh": 1, "pred_kwh": 1, "energy_error_pct": 1})
    print("\nTest-set results (same test months for both setups)")
    print(show.to_string(index=False))

    for h in HOUSES:
        m = (test["house"] == h).to_numpy()
        pred = pd.Series(chrono["lightgbm"][m], index=pd.DatetimeIndex(test.loc[m, "time"]))
        frames[h]["pred"] = pred.reindex(frames[h].index)

    importance = plot_importance(model, FIG_DIR / "model_feature_importance.png")
    print("\nTop 10 features by gain (%)")
    print(importance.head(10).round(1).to_string())

    plot_actual_vs_pred(frames, FIG_DIR / "model_actual_vs_pred.png")
    fail_house, fail_start, other, other_kwh = plot_failure(frames, FIG_DIR / "model_failure_case.png")
    print(f"\nFailure-case window: House {fail_house} from {fail_start}, "
          f"biggest other metered heater there: {other} ({other_kwh:.2f} kWh in the window)")

    fp = false_positive_report(frames)
    print("\nFalse 'on' minutes and other heating appliances (chronological model, test period)")
    print(fp.to_string(index=False))

    per_cycle, recall = cycle_recall(frames)
    print("\nCycle-level recall (cycle caught if >= 50% of its minutes are predicted on)")
    print(recall.to_string(index=False))

    splits.to_csv(TABLE_DIR / "model_splits.csv", index=False)
    show.to_csv(TABLE_DIR / "model_metrics.csv", index=False)
    importance.round(2).to_csv(TABLE_DIR / "model_feature_importance.csv", header=["gain_pct"])
    fp.to_csv(TABLE_DIR / "model_false_on.csv", index=False)
    recall.to_csv(TABLE_DIR / "model_cycle_recall.csv", index=False)
    per_cycle.to_csv(TABLE_DIR / "model_test_cycles.csv", index=False)
    out = test[["time", "house", "wm"]].copy()
    out["pred_chronological"] = chrono["lightgbm"]
    out["pred_leave_one_house_out"] = loho["lightgbm"]
    out.to_parquet(OUT_DIR / "test_predictions.parquet", index=False)
    print(f"\nSaved tables in {TABLE_DIR}, figures in {FIG_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train and evaluate the washing machine disaggregation model")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="folder that holds raw/ and clean/")
    main(parser.parse_args().data_dir)
