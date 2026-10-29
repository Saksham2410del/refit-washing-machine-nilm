"""Part 1: inspect and clean the raw REFIT data for House 1, then resample to 1 minute.

Usage: python src/clean_house1.py [--data-dir PATH]
"""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import (AGG_COLOR, BAD_COLOR, CLEAN_LOCAL_FROM, DATA_DIR, FIG_DIR, OUT_DIR, TABLE_DIR, WM_CHANNEL,
                    WM_COLOR, find_csv, read_refit_csv, setup_plots, true_runs, uk_time)

HOUSE = 1
CLOCK_CHANGES = ["2013-10-27", "2014-03-30", "2014-10-26", "2015-03-29"]   # UK clocks change at 01:00 UTC
POWER_COLS = ["Aggregate"] + [f"Appliance{i}" for i in range(1, 10)]
AGG_MAX_W = 25_000   # a UK home on a 100 A main fuse tops out around 23 kW
IAM_MAX_W = 4_000    # plug monitors sit on 13 A sockets (~3.1 kW); same cut-off the official cleaning used
MAX_FILL_MIN = 5     # forward-fill gaps up to 5 minutes, anything longer is flagged as an outage
PLOT_CHANNELS = {"Aggregate": "Aggregate", "Appliance1": "Fridge (ch 1)", "Appliance5": "Washing machine (ch 5)"}


def load_raw(raw_dir):
    """Read every raw csv for House 1 (the archive splits a house into _Part1 / _Part2)."""
    files = [p for p in find_csv(raw_dir, rf"house[_ ]?{HOUSE}(?!\d)") if not p.name.upper().startswith("CLEAN")]
    if not files:
        raise FileNotFoundError(f"no raw csv for House {HOUSE} under {raw_dir}")
    parts = []
    for path in files:
        df = read_refit_csv(path)
        df["file"] = path.name
        print(f"  read {path.name}: {len(df):,} rows")
        parts.append(df)
    return pd.concat(parts, ignore_index=True)


def audit_raw(df):
    """Count timestamp and value problems in the raw data, before changing anything."""
    unix = pd.to_numeric(df["Unix"], errors="coerce")
    uk = pd.Series(uk_time(unix), index=df.index)
    checks = {
        "files": df["file"].nunique(),
        "rows": len(df),
        "first_reading": uk.min(),
        "last_reading": uk.max(),
        "unparseable_unix": int(unix.isna().sum()),
    }

    # the DATETIME text should be the same clock time as UNIX (the logger rounds, so allow 1 s)
    text_time = pd.to_datetime(df["Time"], errors="coerce")
    diff_s = (text_time - pd.to_datetime(unix, unit="s")).dt.total_seconds().abs()
    checks["unparseable_datetime_text"] = int(text_time.isna().sum())
    checks["datetime_text_off_by_over_1s"] = int((diff_s > 1).sum())
    checks["rows_in_repeated_autumn_hour"] = int((uk.isna() & unix.notna()).sum())

    step = unix.diff()
    checks["out_of_order_rows"] = int((step < 0).sum())
    checks["largest_backward_jump_s"] = float(-step.min()) if (step < 0).any() else 0.0

    dup_time = df.duplicated("Unix")
    same_ts = df[df.duplicated("Unix", keep=False)]
    n_identical = int(same_ts.duplicated(["Unix"] + POWER_COLS).sum())
    checks["duplicate_timestamps"] = int(dup_time.sum())
    checks["duplicates_identical_values"] = n_identical
    checks["duplicates_different_values"] = int(dup_time.sum()) - n_identical

    t = np.sort(unix.dropna().unique())
    gaps = np.diff(t)
    checks["median_interval_s"] = float(np.median(gaps))
    checks["intervals_6_to_10s_pct"] = round(100 * float(np.mean((gaps >= 6) & (gaps <= 10))), 2)
    checks["intervals_under_6s_pct"] = round(100 * float(np.mean(gaps < 6)), 2)
    checks["gaps_over_1min"] = int((gaps > 60).sum())
    checks["gaps_over_5min"] = int((gaps > 300).sum())
    checks["gaps_over_1h"] = int((gaps > 3600).sum())
    checks["gaps_over_1day"] = int((gaps > 86400).sum())

    order = np.argsort(gaps)[::-1][:5]
    longest = pd.DataFrame({
        "gap_start": uk_time(t[order]),
        "gap_end": uk_time(t[order + 1]),
        "hours": np.round(gaps[order] / 3600, 2),
    })

    file_rows = []
    for name, part in df.groupby("file"):
        t_part = uk.loc[part.index]
        file_rows.append({"file": name, "rows": len(part), "first": t_part.min(), "last": t_part.max(),
                          "agg_missing": int(part["Aggregate"].isna().sum()),
                          "agg_zero": int((part["Aggregate"] == 0).sum())})

    channel_rows = []
    for col in POWER_COLS:
        limit = AGG_MAX_W if col == "Aggregate" else IAM_MAX_W
        s = df[col]
        channel_rows.append({"channel": col, "missing": int(s.isna().sum()), "zero": int((s == 0).sum()),
                             "negative": int((s < 0).sum()), "over_limit": int((s > limit).sum()),
                             "limit_w": limit, "max_w": float(s.max())})

    return checks, pd.DataFrame(file_rows), pd.DataFrame(channel_rows), longest


def clock_change_steps(df):
    """UNIX steps around each UK clock change, per file, in the order the rows were logged.

    If UNIX were true UTC nothing would happen at these moments. A one-hour gap in spring and
    a one-hour step back in autumn mean the column holds UK local clock time.
    """
    rows = []
    for name, part in df.groupby("file"):
        u = pd.to_numeric(part["Unix"], errors="coerce").to_numpy()
        for day in CLOCK_CHANGES:
            t0 = pd.Timestamp(f"{day} 01:00").timestamp()
            near = (u > t0 - 3 * 3600) & (u < t0 + 3 * 3600)
            if near.sum() < 100:
                continue
            steps = np.diff(u[near])
            rows.append({"file": name, "clock_change": day, "largest_gap_s": int(steps.max()),
                         "largest_step_back_s": int(max(0, -steps.min()))})
    return pd.DataFrame(rows)


def fill_short_gaps(s, max_len):
    """Forward-fill gaps of up to max_len minutes; longer gaps stay NaN.

    REFIT sensors only log when the load changes, so holding the last value is the
    natural guess for a short gap. pandas' ffill(limit=5) would also fill the first
    5 minutes of a long outage, which is why each gap is measured first.
    """
    short = np.zeros(len(s), dtype=bool)
    for start, end in true_runs(s.isna()):
        if end - start + 1 <= max_len:
            short[start:end + 1] = True
    return s.where(~short, s.ffill())


def clean_raw(df):
    """Sort, merge duplicates, drop impossible values, resample to 1 minute and fill short gaps."""
    df = df.copy()
    df["Unix"] = pd.to_numeric(df["Unix"], errors="coerce")
    df = df.dropna(subset=["Unix"])

    # 1+2. groupby sorts by time and merges rows that share a timestamp (mean of their readings)
    df = df.groupby("Unix")[POWER_COLS].mean()
    # raw UNIX is UK local clock time; the repeated autumn hour cannot be placed and is dropped
    df.index = uk_time(df.index.to_numpy())
    df = df[df.index.notna()]

    # 3. impossible values become NaN so they cannot leak into the minute averages
    n_removed = 0
    removed_plotted = pd.Series(0, index=df.index)    # used to pick the before/after plot window
    for col in POWER_COLS:
        limit = AGG_MAX_W if col == "Aggregate" else IAM_MAX_W
        bad = (df[col] < 0) | (df[col] > limit)
        n_removed += int(bad.sum())
        if col in PLOT_CHANNELS:
            removed_plotted += bad.astype(int)
        df.loc[bad, col] = np.nan
    # a house never draws exactly 0 W; the Part1 files use 0 when the clamp was offline
    agg_zero = df["Aggregate"] == 0
    df.loc[agg_zero, "Aggregate"] = np.nan

    # 4. one value per minute: the mean of the ~7-8 readings inside it
    df_1m = df.resample("1min").mean()
    readings_per_min = df["Aggregate"].resample("1min").count()

    # 5. short gaps -> forward fill, long gaps -> stay NaN and get flagged
    clean = df_1m.copy()
    for col in POWER_COLS:
        clean[col] = fill_short_gaps(df_1m[col], MAX_FILL_MIN)
    clean["is_filled"] = df_1m["Aggregate"].isna() & clean["Aggregate"].notna()
    clean["is_outage"] = clean["Aggregate"].isna()

    stats = {
        "unique_timestamps": len(df),
        "values_removed_negative_or_over_limit": n_removed,
        "aggregate_zero_set_missing": int(agg_zero.sum()),
        "mean_readings_per_minute": round(float(readings_per_min[readings_per_min > 0].mean()), 2),
    }
    return clean, removed_plotted.resample("1min").sum(), stats


def compare_with_official(clean, data_dir):
    """Check our cleaned House 1 against the official cleaned file, minute by minute."""
    files = find_csv(data_dir / "clean", rf"^CLEAN_House{HOUSE}\.csv$")
    if not files:
        return None, 0, {}
    off = read_refit_csv(files[0], usecols=["Unix"] + POWER_COLS)
    off.index = uk_time(off["Unix"], utc_before=CLEAN_LOCAL_FROM)
    off = off[off.index.notna()].drop(columns="Unix").sort_index().resample("1min").mean()

    both = clean.index.intersection(off.index)
    if len(both) == 0:
        return None, 0, {}
    ours, theirs = clean.loc[both], off.loc[both]

    # if both time bases are handled right, the best offset is 0 in every month
    offsets = {}
    for month in sorted(set(both.strftime("%Y-%m"))):
        o = ours.loc[month, "Aggregate"]
        best, best_corr = None, -2.0
        for lag in (-60, 0, 60):
            th = off["Aggregate"].shift(-lag).reindex(o.index)
            ok = o.notna() & th.notna()
            if ok.sum() > 1000:
                corr = o[ok].corr(th[ok])
                if corr > best_corr:
                    best, best_corr = lag, corr
        offsets[month] = best
    rows = []
    for col in POWER_COLS:
        ok = ours[col].notna() & theirs[col].notna()
        diff = (ours.loc[ok, col] - theirs.loc[ok, col]).abs()
        rows.append({"channel": col, "minutes_compared": int(ok.sum()),
                     "mae_w": round(float(diff.mean()), 1),
                     "within_10w_pct": round(100 * float((diff <= 10).mean()), 1),
                     "corr": round(float(ours.loc[ok, col].corr(theirs.loc[ok, col])), 3)})
    # minutes we call an outage but the official file has a value for (it forward-fills gaps)
    filled_by_official = int((ours["is_outage"] & theirs["Aggregate"].notna()).sum())
    return pd.DataFrame(rows), filled_by_official, offsets


def outage_table(clean):
    rows = []
    for start, end in true_runs(clean["is_outage"]):
        rows.append({"start": clean.index[start], "end": clean.index[end], "minutes": end - start + 1})
    return pd.DataFrame(rows, columns=["start", "end", "minutes"])


def pick_window(clean, removed_per_min, hours=12):
    """12 hours that show the cleaning at work: removed glitches, an outage and a wash.

    A removed glitch on a plotted channel counts most, then an outage start, then a filled
    minute. Only windows that are at least half data and contain 15+ washing-machine minutes
    are considered, so every panel has something to look at.
    """
    n = hours * 60
    outage_start = clean["is_outage"] & ~clean["is_outage"].shift(1, fill_value=False)
    events = (100 * removed_per_min.reindex(clean.index, fill_value=0) + 10 * outage_start.astype(int)
              + clean["is_filled"].astype(int))
    score = events.rolling(n).sum().fillna(0)
    data_share = (~clean["is_outage"]).rolling(n).mean()
    wm_minutes = (clean[f"Appliance{WM_CHANNEL[HOUSE]}"] >= 20).rolling(n).sum()
    ok = (data_share >= 0.5) & (wm_minutes >= 15)
    if not ok.any():
        ok = data_share >= 0.5
    end = score.where(ok, 0).idxmax()
    return end - pd.Timedelta(minutes=n - 1), end


def plot_before_after(raw, clean, start, end, path):
    raw_t = pd.Series(uk_time(pd.to_numeric(raw["Unix"], errors="coerce")), index=raw.index)
    in_win = (raw_t >= start) & (raw_t < end + pd.Timedelta(minutes=1))
    raw_w = raw.loc[in_win].assign(t=raw_t[in_win].dt.tz_localize(None)).sort_values("t")
    clean_w = clean.loc[start:end]
    x = clean_w.index.tz_localize(None)

    fig, axes = plt.subplots(len(PLOT_CHANNELS), 2, figsize=(12, 7.5), sharex=True)
    for row, (col, label) in enumerate(PLOT_CHANNELS.items()):
        ax_raw, ax_clean = axes[row]
        ax_raw.plot(raw_w["t"], raw_w[col], ".", ms=1.5, color=AGG_COLOR)
        ax_clean.plot(x, clean_w[col], color=WM_COLOR, lw=1)
        for s, e in true_runs(clean_w["is_outage"]):
            ax_clean.axvspan(x[s], x[e], color=BAD_COLOR, alpha=0.25, lw=0)
        ax_raw.set_ylabel(f"{label} (W)")
    axes[0, 0].set_title("Raw readings (~8 s, as recorded)")
    axes[0, 1].set_title("Cleaned: 1-min mean, short gaps filled, outages shaded red")
    for ax in axes[-1]:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
    fig.suptitle(f"House {HOUSE}: raw vs cleaned, {start:%d %b %Y %H:%M} to {end:%d %b %H:%M}")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def plot_coverage(clean, path):
    daily = (~clean["is_outage"]).resample("1D").mean() * 100
    colors = [BAD_COLOR if v < 50 else WM_COLOR for v in daily]
    fig, ax = plt.subplots(figsize=(12, 3))
    ax.bar(daily.index.tz_localize(None), daily.to_numpy(), width=1.0, align="edge", color=colors)
    ax.set_ylim(0, 105)
    ax.set_ylabel("% of minutes with data")
    ax.set_title(f"House {HOUSE}: daily coverage of the aggregate after cleaning (red = under 50%)")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main(data_dir):
    setup_plots()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    TABLE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Loading raw House {HOUSE} from {data_dir / 'raw'}")
    raw = load_raw(data_dir / "raw")

    checks, by_file, channels, longest = audit_raw(raw)
    print("\nRaw data audit (before cleaning)")
    for key, value in checks.items():
        print(f"  {key:<34} {value}")
    print("\nPer file")
    print(by_file.to_string(index=False))
    print(f"\nPer channel (impossible = negative, or over {AGG_MAX_W} W aggregate / {IAM_MAX_W} W appliance)")
    print(channels.to_string(index=False))
    print("\nFive longest gaps between readings")
    print(longest.to_string(index=False))
    clock = clock_change_steps(raw)
    print("\nUNIX steps around the UK clock changes (a 1 h gap in spring / step back in autumn = local time)")
    print(clock.to_string(index=False))

    clean, removed_per_min, stats = clean_raw(raw)
    outages = outage_table(clean)
    stats["minutes_total"] = len(clean)
    stats["minutes_filled_short_gap"] = int(clean["is_filled"].sum())
    stats["minutes_outage"] = int(clean["is_outage"].sum())
    stats["outage_pct"] = round(100 * clean["is_outage"].mean(), 2)
    stats["outage_periods"] = len(outages)
    stats["outage_periods_over_1h"] = int((outages["minutes"] > 60).sum())
    stats["longest_outage_days"] = round(outages["minutes"].max() / 1440, 2) if len(outages) else 0
    print("\nAfter cleaning (1-minute data)")
    for key, value in stats.items():
        print(f"  {key:<38} {value}")
    print("\nStill missing after cleaning, % of minutes per channel")
    print(clean[POWER_COLS].isna().mean().mul(100).round(2).to_string())
    print("\nTen longest outages")
    print(outages.sort_values("minutes", ascending=False).head(10).to_string(index=False))

    official, filled_by_official, offsets = compare_with_official(clean, data_dir)
    if official is None:
        print("\nCLEAN_House1.csv not found (or no overlapping minutes), skipped the comparison with the official cleaning")
    else:
        print("\nOur 1-minute House 1 vs the official cleaned House 1 (minutes where both have data)")
        print(official.to_string(index=False))
        print(f"  minutes we flag as outage that the official file fills in: {filled_by_official:,}")
        not_zero = {m: lag for m, lag in offsets.items() if lag != 0}
        print(f"  months where the two line up with no time offset: {len(offsets) - len(not_zero)} of {len(offsets)}"
              + (f", others: {not_zero}" if not_zero else ""))
        official.to_csv(TABLE_DIR / "house1_vs_official.csv", index=False)
    clock.to_csv(TABLE_DIR / "house1_clock_changes.csv", index=False)

    clean.to_parquet(OUT_DIR / "house1_clean_1min.parquet")
    pd.Series({**checks, **stats}).to_csv(TABLE_DIR / "house1_audit.csv", header=["value"])
    channels.to_csv(TABLE_DIR / "house1_channel_audit.csv", index=False)
    outages.sort_values("minutes", ascending=False).to_csv(TABLE_DIR / "house1_outages.csv", index=False)

    start, end = pick_window(clean, removed_per_min)
    plot_before_after(raw, clean, start, end, FIG_DIR / "house1_before_after.png")
    plot_coverage(clean, FIG_DIR / "house1_coverage.png")
    print(f"\nBefore/after plot window: {start} to {end}")
    print(f"Saved {OUT_DIR / 'house1_clean_1min.parquet'}, tables in {TABLE_DIR}, figures in {FIG_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean raw REFIT House 1 data")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="folder that holds raw/ and clean/")
    main(parser.parse_args().data_dir)
