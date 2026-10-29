"""Part 2: washing-machine exploratory analysis on the official cleaned REFIT data.

Usage: python src/eda_washing_machine.py [--data-dir PATH]
"""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from common import (AGG_COLOR, DATA_DIR, FIG_DIR, HEATED_W, HOUSES, MAX_ISSUE_SHARE, ON_W, TABLE_DIR, WM_CHANNEL,
                    WM_COLOR, detect_cycles, frozen_mask, house_color, load_clean_house, setup_plots, silent_mask,
                    stuck_mask, true_runs)

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PEAK_HOURS = range(16, 19)   # 16:00-19:00, the usual UK time-of-use peak


def summarise(house, df, cycles):
    """Availability and data quality for one house."""
    valid = df["agg"].notna() & df["wm"].notna() & ~df["frozen"] & ~df["wm_stuck"] & ~df["wm_silent"]
    wm = df.loc[valid, "wm"]
    weeks = valid.sum() / (60 * 24 * 7)
    return {
        "house": house,
        "wm_channel": WM_CHANNEL[house],
        "start": df.index[0].strftime("%Y-%m-%d"),
        "end": df.index[-1].strftime("%Y-%m-%d"),
        "days": round(len(df) / 1440, 1),
        "missing_pct": round(100 * (df["agg"].isna() | df["wm"].isna()).mean(), 2),
        "frozen_pct": round(100 * df["frozen"].mean(), 2),
        "wm_stuck_pct": round(100 * df["wm_stuck"].mean(), 2),
        # only count minutes that had readings; most silent stretches sit inside outages anyway
        "wm_silent_pct": round(100 * (df["wm_silent"] & df["wm"].notna() & df["agg"].notna()).mean(), 2),
        "issues_any_pct": round(100 * (df["issues"] > 0).mean(), 2),
        "issues_most_pct": round(100 * (df["issues"] > MAX_ISSUE_SHARE).mean(), 2),
        "wm_zero_pct": round(100 * (wm == 0).mean(), 2),
        "wm_off_pct": round(100 * (wm < ON_W).mean(), 2),
        "cycles": len(cycles),
        "cycles_per_week": round(len(cycles) / weeks, 2),
        "wm_kwh_per_week": round(cycles["energy_kwh"].sum() / weeks, 2),
    }


def cycle_stats(cycles):
    """Median and inter-quartile range of the cycle characteristics, per house."""
    rows = []
    for house, c in list(cycles.groupby("house")) + [("all", cycles)]:
        row = {"house": house, "cycles": len(c)}
        for col in ["duration_min", "energy_kwh", "peak_w"]:
            q1, med, q3 = c[col].quantile([0.25, 0.5, 0.75])
            row[f"{col}_median"] = round(med, 2)
            row[f"{col}_iqr"] = f"{q1:.2f}-{q3:.2f}"
        row["heated_pct"] = round(100 * (c["peak_w"] >= HEATED_W).mean(), 1)
        row["heater_energy_pct"] = round(100 * c["heater_kwh"].sum() / c["energy_kwh"].sum(), 1)
        row["joined_pauses_pct"] = round(100 * (c["n_parts"] > 1).mean(), 1)
        rows.append(row)
    return pd.DataFrame(rows)


def coarse_peak(wm, cycles, freq):
    """Highest `freq` average of washing-machine power inside each cycle, i.e. what a smart meter would see."""
    coarse = wm.resample(freq).mean()
    peaks = []
    for start, end in zip(cycles["start"], cycles["end"]):
        # floor in UTC so the daylight-saving change cannot make the time ambiguous
        first = start.tz_convert("UTC").floor(freq).tz_convert(start.tz)
        peaks.append(coarse.loc[first:end].max())
    return peaks


def resolution_table(frames, cycles):
    """1-min vs 15-min vs 30-min view of the same cycles, next to a normal evening for the whole house."""
    rows, evenings = [], []
    for house, df in frames.items():
        agg_30 = df["agg"].where(~df["frozen"]).resample("30min").mean()
        evenings.append(agg_30[agg_30.index.hour.isin(range(17, 22))])
        rows.append(resolution_row(house, cycles[cycles["house"] == house], evenings[-1]))
    rows.append(resolution_row("all", cycles, pd.concat(evenings)))
    return pd.DataFrame(rows)


def resolution_row(house, c, evening):
    return {"house": house,
            "peak_1min_w_median": round(c["peak_w"].median()),
            "peak_15min_w_median": round(c["peak_15min_w"].median()),
            "peak_30min_w_median": round(c["peak_30min_w"].median()),
            "house_evening_30min_w_median": round(evening.median()),
            "house_evening_30min_w_p90": round(evening.quantile(0.9))}


def pause_sensitivity(wm_by_house):
    """How the cycle count depends on the pause we allow inside one wash."""
    rows = []
    for house, wm in wm_by_house.items():
        row = {"house": house, "raw_on_periods": len(true_runs(wm.fillna(0) >= ON_W))}
        for pause in [0, 5, 10, 15, 30]:
            row[f"pause_{pause}min"] = len(detect_cycles(wm, max_pause=pause))
        rows.append(row)
    return pd.DataFrame(rows)


def pick_cycle(cycles, mask=None):
    """The cycle whose energy is closest to the median, among those matching mask."""
    cand = cycles
    if mask is not None and mask.any():
        cand = cycles[mask]
    pos = (cand["energy_kwh"] - cand["energy_kwh"].median()).abs().to_numpy().argmin()
    return cand.iloc[pos]


def plot_day_trace(house, df, cycles, path):
    """24 h of aggregate and washing machine power on a typical washing day."""
    cycles = cycles.copy()
    cycles["day"] = cycles["start"].dt.normalize()
    per_day = cycles["day"].value_counts()
    missing_by_day = (df["agg"].isna() | df["frozen"]).resample("1D").mean()
    good_days = missing_by_day[missing_by_day < 0.01].index
    ok = cycles["day"].isin(per_day[per_day == 1].index) & cycles["day"].isin(good_days)
    pick = pick_cycle(cycles, ok)

    day0 = pick["day"]
    win = df.loc[day0: day0 + pd.Timedelta(hours=24) - pd.Timedelta(minutes=1)]
    x = win.index.tz_localize(None)
    fig, ax = plt.subplots(figsize=(11, 3.8))
    ax.plot(x, win["agg"], color=AGG_COLOR, lw=0.8, label="Aggregate (whole house)")
    ax.plot(x, win["wm"], color=WM_COLOR, lw=1.2, label="Washing machine")
    ax.axvspan(pick["start"].tz_localize(None), pick["end"].tz_localize(None),
               color=WM_COLOR, alpha=0.1, lw=0, label="Detected cycle")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.set_ylabel("Power (W, 1-min mean)")
    ax.set_title(f"House {house}, {day0:%a %d %b %Y}: aggregate and washing machine "
                 f"(cycle {pick['duration_min']} min, {pick['energy_kwh']:.2f} kWh)")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return pick


def plot_one_cycle(ax, house, df, cyc):
    pad = pd.Timedelta(minutes=20)
    win = df.loc[cyc["start"] - pad: cyc["end"] + pad, "wm"]
    x = win.index.tz_localize(None)
    ax.plot(x, win, color=WM_COLOR, lw=1.2, label="Washing machine")
    ax.axhline(ON_W, color="black", lw=0.8, ls="--", label=f"{ON_W} W on threshold")
    ax.axvspan(cyc["start"].tz_localize(None), cyc["end"].tz_localize(None),
               color=WM_COLOR, alpha=0.08, lw=0, label="Detected cycle")
    label = f"Heater on (>{HEATED_W} W)"
    for s, e in true_runs(win >= HEATED_W):
        ax.axvspan(x[s], x[e], color="#eda100", alpha=0.25, lw=0, label=label)
        label = None
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.set_ylabel("Power (W, 1-min mean)")
    ax.set_title(f"House {house}, {cyc['start']:%d %b %Y}: {cyc['duration_min']} min, "
                 f"{cyc['energy_kwh']:.2f} kWh, {cyc['n_parts']} on-periods joined into one cycle")
    ax.legend(loc="upper right")


def plot_cycle_zoom(frames, cycles, path):
    """Left: a typical heated wash. Right: a typical wash that needed pauses bridged."""
    house_a, house_b = HOUSES[0], HOUSES[1]
    ca = cycles[cycles["house"] == house_a]
    cb = cycles[cycles["house"] == house_b]
    cyc_a = pick_cycle(ca, ca["peak_w"] >= HEATED_W)
    cyc_b = pick_cycle(cb, cb["n_parts"] >= 3)
    fig, axes = plt.subplots(2, 1, figsize=(11, 7))
    plot_one_cycle(axes[0], house_a, frames[house_a], cyc_a)
    plot_one_cycle(axes[1], house_b, frames[house_b], cyc_b)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return cyc_a, cyc_b


def plot_cross_house(cycles, hour_share, day_share, path):
    labels = [f"House {h}" for h in HOUSES]
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    for ax, col, title in [(axes[0, 0], "energy_kwh", "Energy per cycle (kWh)"),
                           (axes[0, 1], "duration_min", "Cycle duration (min)")]:
        data = [cycles.loc[cycles["house"] == h, col] for h in HOUSES]
        bp = ax.boxplot(data, tick_labels=labels, patch_artist=True, medianprops={"color": "black"},
                        flierprops={"markersize": 2, "markeredgecolor": AGG_COLOR})
        for patch, h in zip(bp["boxes"], HOUSES):
            patch.set_facecolor(house_color(h))
            patch.set_alpha(0.6)
        ax.set_title(title)

    for h in HOUSES:
        axes[1, 0].plot(hour_share.index, hour_share[h], color=house_color(h), lw=2, label=f"House {h}")
        axes[1, 1].plot(DAYS, day_share[h], color=house_color(h), lw=2, marker="o", ms=4, label=f"House {h}")
    axes[1, 0].axvspan(PEAK_HOURS[0], PEAK_HOURS[-1] + 1, color=AGG_COLOR, alpha=0.15, lw=0)
    axes[1, 0].set_xticks(range(0, 24, 3))
    axes[1, 0].set_xlabel("Hour of day when the cycle starts (shaded: 16:00-19:00 peak)")
    axes[1, 0].set_ylabel("% of the house's cycles")
    axes[1, 0].set_title("Start time of day")
    axes[1, 1].set_ylabel("% of the house's cycles")
    axes[1, 1].set_title("Day of week")
    axes[1, 0].legend()
    axes[1, 1].legend()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main(data_dir):
    setup_plots()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    TABLE_DIR.mkdir(parents=True, exist_ok=True)

    frames, wm_by_house, all_cycles, summary = {}, {}, [], []
    for house in HOUSES:
        print(f"Loading House {house} (washing machine = Appliance{WM_CHANNEL[house]})")
        df = load_clean_house(house, data_dir)
        df["frozen"] = frozen_mask(df["agg"])
        df["wm_stuck"] = stuck_mask(df["wm"])
        df["wm_silent"] = silent_mask(df["wm"])
        # flat forward-filled stretches must not become fake cycles, dead monitors are not "off"
        wm = df["wm"].where(~df["frozen"] & ~df["wm_stuck"] & ~df["wm_silent"])
        cycles = detect_cycles(wm)
        cycles["peak_15min_w"] = coarse_peak(wm, cycles, "15min")
        cycles["peak_30min_w"] = coarse_peak(wm, cycles, "30min")
        cycles.insert(0, "house", house)
        summary.append(summarise(house, df, cycles))
        frames[house], wm_by_house[house] = df, wm
        all_cycles.append(cycles)

    cycles = pd.concat(all_cycles, ignore_index=True)
    cycles["start_hour"] = cycles["start"].dt.hour
    cycles["weekday"] = cycles["start"].dt.dayofweek
    summary = pd.DataFrame(summary)
    stats = cycle_stats(cycles)
    sens = pause_sensitivity(wm_by_house)
    resolution = resolution_table(frames, cycles)

    hour_share = pd.crosstab(cycles["start_hour"], cycles["house"], normalize="columns").mul(100)
    hour_share = hour_share.reindex(range(24), fill_value=0)
    day_share = pd.crosstab(cycles["weekday"], cycles["house"], normalize="columns").mul(100)
    day_share = day_share.reindex(range(7), fill_value=0)

    # share of each house's washing machine energy used in the 16:00-19:00 peak
    peak_rows = []
    total_wmin, peak_wmin = 0.0, 0.0
    for house, wm in wm_by_house.items():
        on = wm[wm >= ON_W]
        in_peak = on.index.hour.isin(PEAK_HOURS)
        total_wmin += float(on.sum())
        peak_wmin += float(on[in_peak].sum())
        peak_rows.append({"house": house,
                          "cycle_starts_in_peak_pct": round(float(hour_share.loc[list(PEAK_HOURS), house].sum()), 1),
                          "wm_energy_in_peak_pct": round(100 * float(on[in_peak].sum()) / float(on.sum()), 1),
                          "weekend_cycles_pct": round(float(day_share.loc[[5, 6], house].sum()), 1)})
    peak_rows.append({"house": "all",
                      "cycle_starts_in_peak_pct": round(100 * float(cycles["start_hour"].isin(PEAK_HOURS).mean()), 1),
                      "wm_energy_in_peak_pct": round(100 * peak_wmin / total_wmin, 1),
                      "weekend_cycles_pct": round(100 * float(cycles["weekday"].isin([5, 6]).mean()), 1)})
    peak = pd.DataFrame(peak_rows)

    pd.set_option("display.width", 200)
    print(f"\nCycle rule: on when >= {ON_W} W, pauses <= 15 min joined, keep cycles >= 15 min and >= 0.05 kWh")
    print("\nAvailability and data quality (percentages are of minutes)")
    print(summary.to_string(index=False))
    print("\nCycle characteristics per house")
    print(stats.to_string(index=False))
    print("\nCycle count vs allowed pause (raw_on_periods = plain threshold, nothing joined or filtered)")
    print(sens.to_string(index=False))
    print("\nPeak-time and weekend use")
    print(peak.to_string(index=False))
    print("\nSame cycles seen at 1, 15 and 30 minutes (median highest average inside a cycle, W)")
    print(resolution.to_string(index=False))
    print("\nShare of cycle starts by hour of day (%)")
    print(hour_share.round(1).T.to_string())
    print("\nShare of cycle starts by day of week (%), Mon..Sun")
    print(day_share.round(1).set_axis(DAYS).T.to_string())

    summary.to_csv(TABLE_DIR / "wm_summary.csv", index=False)
    stats.to_csv(TABLE_DIR / "wm_cycle_stats.csv", index=False)
    sens.to_csv(TABLE_DIR / "wm_pause_sensitivity.csv", index=False)
    peak.to_csv(TABLE_DIR / "wm_peak_use.csv", index=False)
    resolution.to_csv(TABLE_DIR / "wm_resolution.csv", index=False)
    hour_share.round(2).to_csv(TABLE_DIR / "wm_hour_share.csv")
    day_share.round(2).set_axis(DAYS).to_csv(TABLE_DIR / "wm_weekday_share.csv")
    cycles.to_csv(TABLE_DIR / "wm_cycles.csv", index=False)

    day_pick = plot_day_trace(HOUSES[0], frames[HOUSES[0]], cycles[cycles["house"] == HOUSES[0]],
                              FIG_DIR / "eda_24h_trace.png")
    cyc_a, cyc_b = plot_cycle_zoom(frames, cycles, FIG_DIR / "eda_cycle_zoom.png")
    plot_cross_house(cycles, hour_share, day_share, FIG_DIR / "eda_cross_house.png")
    print(f"\n24 h trace: House {HOUSES[0]} on {day_pick['start']:%Y-%m-%d}")
    print(f"Zoomed cycles: House {HOUSES[0]} at {cyc_a['start']}, House {HOUSES[1]} at {cyc_b['start']}")
    print(f"Saved tables in {TABLE_DIR} and figures in {FIG_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Washing machine EDA on cleaned REFIT data")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="folder that holds raw/ and clean/")
    main(parser.parse_args().data_dir)
