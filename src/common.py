"""Paths, settings and small helpers shared by the three scripts."""
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"          # expects data/raw and data/clean, see README
OUT_DIR = ROOT / "outputs"
FIG_DIR = OUT_DIR / "figures"
TABLE_DIR = OUT_DIR / "tables"

TZ = "Europe/London"
COLUMNS = ["Time", "Unix", "Aggregate"] + [f"Appliance{i}" for i in range(1, 10)]

# The UNIX column does not mean the same thing everywhere (see DATA.md). The raw files hold
# UK local clock time. The clean files hold true UTC up to the end of September 2014, when
# the first logging database ends (the raw _Part1 files), and UK local time after that.
CLEAN_LOCAL_FROM = pd.Timestamp("2014-10-01")

# washing machine channel per house, from CLEAN_READ_ME_081116.txt
# (House 4 has two machines on channels 4 and 5, so it is left out)
WM_CHANNEL = {1: 5, 2: 2, 3: 6, 5: 3, 6: 2, 7: 5, 8: 4, 9: 3, 10: 5, 11: 3,
              13: 3, 15: 3, 16: 5, 17: 4, 18: 5, 19: 2, 20: 4, 21: 3}
HOUSES = [1, 2, 3, 5, 11]

# other metered appliances with a heating element; only used to explain model errors
OTHER_HEATERS = {
    1: {"washer_dryer": 4, "dishwasher": 6, "electric_heater": 9},
    2: {"dishwasher": 3, "kettle": 8},
    3: {"tumble_dryer": 4, "dishwasher": 5, "kettle": 9},
    5: {"tumble_dryer": 2, "dishwasher": 4, "kettle": 8},
    7: {"tumble_dryer": 4, "dishwasher": 6, "kettle": 9},
    11: {"dishwasher": 4, "kettle": 7},
}

# washing machine cycle rule, explained in RESULTS.md
ON_W = 20            # above standby and sensor noise (same on-threshold as Kelly & Knottenbelt 2015)
MAX_PAUSE_MIN = 15   # soak / drain / refill pauses inside one wash
MIN_CYCLE_MIN = 15   # anything shorter is a door-lock blip or a test spin, not a wash
MIN_CYCLE_KWH = 0.05
HEATED_W = 1000      # a cycle whose 1-min peak passes this used the water heater

# The readme's Issues flag marks readings where the appliance monitors add up to more than
# the aggregate. The sensors are not synchronised, so single flagged readings show up every
# time something switches on; a minute is only treated as bad when most of it is flagged.
MAX_ISSUE_SHARE = 0.5

# plot colours; a house keeps the same colour in every figure
HOUSE_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
AGG_COLOR = "#9a9893"
WM_COLOR = "#2a78d6"
PRED_COLOR = "#eb6834"
OTHER_COLOR = "#6250d6"
BAD_COLOR = "#d03b3b"


def house_color(house):
    return HOUSE_COLORS[HOUSES.index(house) % len(HOUSE_COLORS)]


def setup_plots():
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 130, "font.size": 9,
        "axes.grid": True, "grid.alpha": 0.3, "grid.linewidth": 0.6,
        "axes.spines.top": False, "axes.spines.right": False,
    })


def find_csv(folder, pattern):
    """All csv files under folder (any depth) whose name matches the regex."""
    regex = re.compile(pattern, re.IGNORECASE)
    return sorted(p for p in Path(folder).rglob("*.csv") if regex.search(p.name))


def read_refit_csv(path, usecols=None):
    """Read one REFIT csv (raw or clean) with standard column names.

    Both versions follow the readme layout: DATETIME, UNIX, Aggregate,
    Appliance1-9, plus Issues in the clean files. Names are set by position,
    so this works whether or not the file has a header row.
    """
    with open(path) as f:
        first = f.readline().strip().split(",")
    if len(first) not in (12, 13):
        raise ValueError(f"{Path(path).name}: expected 12 or 13 columns, found {len(first)}")

    names = COLUMNS + ["Issues"] if len(first) == 13 else COLUMNS
    has_header = not first[1].strip().replace(".", "").isdigit()
    power_cols = [c for c in names if c == "Aggregate" or c.startswith("Appliance")]
    dtypes = {c: "float32" for c in power_cols if usecols is None or c in usecols}
    return pd.read_csv(path, header=0 if has_header else None, names=names,
                       usecols=usecols, dtype=dtypes)


def uk_time(unix, utc_before=None):
    """REFIT UNIX values -> UK time. Values before utc_before are true UTC, the rest local clock time.

    The hour that happens twice when the clocks go back cannot be placed, so it becomes NaT.
    """
    t = pd.DatetimeIndex(pd.to_datetime(np.asarray(unix), unit="s"))
    local = t.tz_localize(TZ, ambiguous="NaT", nonexistent="NaT")
    if utc_before is None:
        return local
    utc = t.tz_localize("UTC").tz_convert(TZ)
    return local.where(t >= utc_before, utc)


def load_clean_house(house, data_dir, extra=None):
    """Load CLEAN_House{n}.csv and return 1-minute mean power on UK local time.

    Columns: agg, wm, issues (share of readings flagged in that minute) and any
    extra channels passed as {name: channel_number}.
    """
    files = find_csv(Path(data_dir) / "clean", rf"^CLEAN_House{house}\.csv$")
    if not files:
        raise FileNotFoundError(f"CLEAN_House{house}.csv not found under {Path(data_dir) / 'clean'}")

    wm_col = f"Appliance{WM_CHANNEL[house]}"
    rename = {"Aggregate": "agg", wm_col: "wm", "Issues": "issues"}
    for name, channel in (extra or {}).items():
        rename[f"Appliance{channel}"] = name

    df = read_refit_csv(files[0], usecols=["Unix"] + list(rename))
    df.index = uk_time(df["Unix"], utc_before=CLEAN_LOCAL_FROM)
    df = df[df.index.notna()].drop(columns="Unix").sort_index()
    return df.resample("1min").mean().rename(columns=rename)


def true_runs(mask):
    """Start and end positions (inclusive) of every run of True values."""
    m = np.concatenate([[False], np.asarray(mask, dtype=bool), [False]])
    edges = np.diff(m.astype(int))
    starts = np.where(edges == 1)[0]
    ends = np.where(edges == -1)[0] - 1
    return list(zip(starts, ends))


def frozen_mask(s, min_len=60):
    """True where a 1-minute series stays exactly constant for min_len+ minutes.

    The clean REFIT files forward-fill missing readings, so an outage can show up
    as a perfectly flat line instead of a gap. A real household aggregate never
    holds the exact same minute average for an hour (the fridge alone moves it).
    """
    run_id = s.diff().ne(0).cumsum()
    run_len = s.groupby(run_id).transform("size")
    return (run_len >= min_len) & s.notna()


def stuck_mask(wm, min_len=60):
    """True where the washing machine monitor holds the same 'on' value for min_len+ minutes.

    A running machine never keeps an exact 1-minute average for an hour (the drum and
    heater keep switching), so this is a monitor that stopped updating and got
    forward-filled. Long exact zeros are normal and are not flagged.
    """
    return frozen_mask(wm, min_len) & (wm >= ON_W)


def silent_mask(wm, min_days=28):
    """True inside stretches of min_days+ days with no washing at all.

    Every home here washes at least about once a week, so four silent weeks while the
    house is still being measured means the monitor was unplugged or moved (House 11
    from late April 2015). Those minutes are unknown, not "off".
    """
    quiet = (wm.fillna(0) < ON_W).to_numpy()
    silent = np.zeros(len(wm), dtype=bool)
    for start, end in true_runs(quiet):
        if end - start + 1 >= min_days * 1440:
            silent[start:end + 1] = True
    return pd.Series(silent, index=wm.index)


def detect_cycles(wm, on_w=ON_W, max_pause=MAX_PAUSE_MIN, min_minutes=MIN_CYCLE_MIN, min_kwh=MIN_CYCLE_KWH):
    """Find washing machine cycles in a 1-minute power series (regular index).

    1. a minute is "on" when power >= on_w (missing minutes count as off)
    2. on-periods separated by a pause of <= max_pause minutes belong to one cycle
    3. a cycle must last >= min_minutes and use >= min_kwh
    """
    power = wm.fillna(0).to_numpy()
    merged = []
    for start, end in true_runs(power >= on_w):
        if merged and start - merged[-1][1] - 1 <= max_pause:
            merged[-1][1] = end
            merged[-1][2] += 1
        else:
            merged.append([start, end, 1])

    rows = []
    for start, end, n_parts in merged:
        seg = power[start:end + 1]
        minutes = end - start + 1
        kwh = float(seg.sum()) / 60 / 1000
        if minutes >= min_minutes and kwh >= min_kwh:
            rows.append({"start": wm.index[start], "end": wm.index[end], "duration_min": minutes,
                         "peak_w": round(float(seg.max()), 1), "energy_kwh": round(kwh, 4),
                         "heater_kwh": round(float(seg[seg >= HEATED_W].sum()) / 60 / 1000, 4),
                         "n_parts": n_parts})
    return pd.DataFrame(rows, columns=["start", "end", "duration_min", "peak_w", "energy_kwh", "heater_kwh", "n_parts"])
