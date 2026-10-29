# REFIT: data cleaning and washing-machine disaggregation

Take-home assignment for Flock Energy. Three scripts take the REFIT data from raw files to an evaluated model:

1. `src/clean_house1.py` audits the raw House 1 data (timestamps, duplicates, gaps, impossible values), cleans it and resamples it to 1 minute.
2. `src/eda_washing_machine.py` analyses washing-machine use in Houses 1, 2, 3, 5 and 11 from the official cleaned data: data quality, a cycle detection rule, cycle statistics and when people wash.
3. `src/train_disaggregation.py` estimates washing-machine power from the whole-house aggregate at 1-minute resolution with LightGBM. It compares the model with two simple baselines on later months of known homes and on homes the model has never seen.

Write-ups:

- [DATA.md](DATA.md): raw data audit, timestamps, cleaning steps, gap and outlier decisions, remaining concerns
- [RESULTS.md](RESULTS.md): washing-machine EDA, model results, validation, failure cases
- [Recommendation.md](Recommendation.md): one-page summary for a utility, plus the Section 4 answers

## Results in short

- **Raw House 1.** The raw data has 8.5 million rows in two overlapping files. It contains 1.2 million duplicate timestamps, 3,276 impossible readings (logger codes such as 65,535 W) and 375 outages, the longest 41.6 days. After cleaning, the 1-minute series matches the official cleaned file with correlation 0.991.
- **The UNIX column is not always UTC.** Raw files hold UK local time. The clean files are UTC until September 2014 and local time after it. This was found by lining up raw and clean files week by week, it is fixed in `common.uk_time()`, and it matters for every hour-of-day result.
- **The cleaned files still needed checking.**
  - Outages were hidden as frozen flat lines (11.7% of House 3's minutes).
  - House 5's washing-machine monitor got stuck.
  - House 11's monitor went dead for its last nine weeks, and reads more than the whole house when heating.
  - All of these are detected and excluded.
- **What a wash looks like.** 2,019 washes in five homes: a typical one lasts 64 minutes and uses 0.45 kWh. 95% heat their own water, and the heater is 76% of all washing-machine energy. Only 13.0% of that energy falls in the 16:00-19:00 peak, about the window's 12.5% share of the day.
- **The model.** LightGBM on 20 backward-looking aggregate features reaches F1 0.41 on later months of known homes, against 0.17 for an hourly-profile baseline and 0 for always-off. On homes it has never seen, F1 is 0.33. Energy totals land within 20% in four of five homes. The model misses most of House 5's washer-dryer drying runs, and its false alarms cluster around kettles, dishwashers and night-time water heating.
- **Recommendation.** Target households that wash hot, since heating is three quarters of the energy and the model sees it best, rather than trying to shift washing out of the peak.

## Repository layout

```
src/
  common.py                  paths, house/channel mapping, timestamps, cycle rule, shared helpers
  clean_house1.py            Part 1: raw House 1 audit, cleaning, 1-minute resample
  eda_washing_machine.py     Part 2: washing-machine EDA on the cleaned data
  train_disaggregation.py    Part 3: features, baselines, LightGBM, evaluation, failure analysis
outputs/
  figures/                   every plot used in the Markdown files
  tables/                    csv version of every table
data/                        not committed; the REFIT files go here (see Setup)
```

## Setup

Tested with Python 3.13 on Windows 11 (pandas 3.0.5, numpy 2.5.1, LightGBM 4.7.0, matplotlib 3.11.1). Python 3.11 or newer should work.

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

On Linux or macOS, activate with `source .venv/bin/activate`.

The data is not in the repository:

1. **Raw data.** Download `REFIT_RAW_081116.7z` (about 670 MB) from the [REFIT dataset page](https://pureportal.strath.ac.uk/en/datasets/refit-electrical-load-measurements/) in a browser; the portal blocks scripted downloads. Extract `RAW_House1_Part1.csv` and `RAW_House1_Part2.csv` into `data/raw/` with 7-Zip.
2. **Cleaned data.** Download `CLEAN_House1.csv`, `CLEAN_House2.csv`, `CLEAN_House3.csv`, `CLEAN_House5.csv` and `CLEAN_House11.csv` into `data/clean/`. The creators publish them one by one on [Zenodo](https://doi.org/10.5281/zenodo.5063428) with MD5 checksums. The same files are inside `CLEAN_REFIT_081116.7z` on the Strathclyde portal. The Zenodo copy has Houses 1-5 and 11, which is why these five homes were picked.
3. **Other locations.** Subfolders are fine, because the scripts search for the files. If the data is somewhere else, pass `--data-dir PATH` to each script, where PATH is the folder that contains `raw/` and `clean/`.

## Run

```
python src/clean_house1.py
python src/eda_washing_machine.py
python src/train_disaggregation.py
```

Each script prints its numbers and writes figures to `outputs/figures/` and tables to `outputs/tables/`. They are independent: Part 1 uses the raw data, and Parts 2 and 3 use the official cleaned data. Run time on a 16-core laptop is about 1 minute for the cleaning, 25 seconds for the EDA and 1.5 minutes for the model (six LightGBM fits).

## What I built and why

**Timestamps.** The readme calls the UNIX column UTC, but the data says otherwise:

- **Raw files hold UK local clock time.** There is a one-hour gap at every spring clock change and a one-hour step back in autumn.
- **Clean files switch convention.** They are UTC until 30 September 2014, when the first logging database ends, and local time after it. This was found by lining up raw and clean files week by week in all five homes.
- **One helper handles both.** `uk_time()` in `common.py` converts each file correctly. After the fix, my cleaned House 1 lines up with the official file with no offset in every month that can be tested, and the model's F1 went up slightly because the hour-of-day feature became consistent.

**Cleaning (Part 1).**

- Sort by time and average readings that share a timestamp.
- Set physically impossible values to missing: negative power, an aggregate above 25 kW, a plug monitor above 4 kW, and an aggregate of exactly 0 W.
- Take the 1-minute mean, forward-fill gaps of up to 5 minutes, and leave longer gaps missing with an `is_outage` flag.

DATA.md gives the reason for each threshold. I did not try to copy everything the official pipeline does, such as re-mapping plug monitors that householders moved. Instead, the script compares my cleaned House 1 with the official file minute by minute.

**Checks on the official cleaned data (Parts 2 and 3).** The cleaned files forward-fill gaps, so problems show up as flat lines rather than holes. Four checks were added, each because the data showed the problem:

- an aggregate frozen at one exact value for 60+ minutes;
- a washing-machine monitor stuck at one exact "on" value for 60+ minutes;
- a monitor silent for 4+ weeks while the house is still measured;
- minutes where most readings carry the readme's Issues flag.

These minutes are left out of cycle detection, training and scoring.

**Cycle rule (Part 2).** A plain `power > threshold` rule cuts one wash into many pieces, because the drum stops while the machine soaks, drains and refills, and the power falls to a few watts. The rule used:

- the machine is on at 20 W or more;
- on-periods separated by a pause of 15 minutes or less belong to the same cycle;
- a cycle has to last at least 15 minutes and use at least 0.05 kWh.

RESULTS.md shows how the number of cycles changes with the allowed pause.

**Model (Part 3).** LightGBM regression predicting the washing machine's 1-minute power from 20 features of the aggregate signal only:

- the current value;
- mean, min, max and standard deviation over the last 5, 15, 30 and 60 minutes;
- the 1-minute and 5-minute change;
- the hour of day.

Why this setup:

- **Gradient-boosted trees are a practical fit.** They train in minutes on a laptop CPU, need no scaling, handle the non-linear pattern (a ~2 kW block followed by an hour of motor noise) well, and their feature importances are easy to explain.
- **Every window looks backwards only,** so the same model could run on a live feed.
- **Small predictions are set to 0.** A regression model hedges with small values when it is unsure, so predictions below a floor (20 to 300 W, picked on the validation data) become 0.

**Baselines.**

- *Always off* predicts 0 W everywhere. The machine is off in 94-98% of minutes, so this baseline gets the smallest overall MAE of all three methods. That is why MAE alone is not enough.
- *Hourly profile* predicts the average washing-machine power for each hour of the day, learned on the training period.

**Validation.** There is no random split, because neighbouring minutes are almost identical and a random split would put near-copies of test rows into training. Two splits are used instead:

- *Chronological.* Each house is split by time: the first 70% of its usable minutes for training, the next 15% for validation (early stopping and the output floor) and the last 15% for testing. One model is trained on the five houses together. This answers "does it keep working for a known home in later months?".
- *Leave one house out.* For each house, a model is trained on the other four houses only and tested on the same test months of the held-out house. This answers "does it work for a new customer with no sub-metered history?", which is the realistic case for a utility.

The features use only the aggregate, never the washing-machine signal, and they only look back in time, so training rows never contain information from the test period. Both setups are scored on exactly the same test minutes, so their numbers can be compared directly.

**Metrics.**

- *MAE (W)* is the standard error, but most of it comes from the many minutes when the machine is off.
- *MAE while running* (true power at least 20 W) shows how well the power level is tracked when it matters.
- *On/off precision, recall and F1 at 20 W* show whether the model knows *when* the machine runs.
- *Energy error (%)* compares predicted and true kWh over the test period, which is what a bill breakdown would show.

## Assumptions

- **Channel mapping.** The readme's mapping holds for the whole period. The readme warns that occupants may have moved monitors. For House 1, every raw channel matches the official cleaned file closely, but other houses were not checked channel by channel.
- **Ground truth.** The washing-machine plug monitor is the ground truth, since it sees only that appliance. House 5's machine (AEG L99695HWD) is a washer-dryer, so its channel includes drying runs.
- **Time.** Times are UK local time after the timestamp fix. Hour-of-day and day-of-week use local time, because people follow the local clock.
- **Resolution.** 1-minute means are detailed enough for this task. Peak power figures are the highest 1-minute mean, not the instantaneous peak.

## Trade-offs

- **Trees on window features vs a sequence model such as seq2point.** Trees are quicker to train, explain and debug. They only see the last hour as summary statistics, though, so they cannot learn the full shape of a 90-minute cycle.
- **Backward-looking windows.** They are leak-free by construction and usable in near real time, but the first minutes of a cycle are harder to catch than with a centred window.
- **Forward fill vs interpolation for short gaps.** Forward fill matches how REFIT logs data (only when the load changes) and never invents a ramp. The cost is that a stale value can be held for up to 5 minutes.
- **Dropping frozen, stuck, silent and mostly-flagged minutes from training and scoring.** This gives cleaner labels, but the evaluation skips some hard periods. For example, two thirds of House 11's heater minutes are dropped, because its monitor reads more than the whole house.
- **One plug limit for all monitors (4 kW).** It is simple and matches the official cleaning, but it lets through glitches that are too big for a fridge yet under 4 kW.
- **Five houses.** This is one more than the brief asks for and still runs in minutes, but five leave-one-house-out folds are a small sample of "new customers".

## AI tools used

I used Claude (an AI assistant) as a coding and writing aid: it helped write and debug the pandas, LightGBM and matplotlib code and tidy the wording of these Markdown files. I set the analysis design (cleaning rules and gap thresholds, the cycle rule, the time-based and leave-one-house-out splits, the metrics). Every number in these reports comes straight from the scripts' output and can be reproduced with the three commands above.

## What I would do next

1. **Add forward-looking windows for offline use.** A quick side test (not in the scripts) with the next 15, 30 and 60 minutes raised chronological F1 from 0.41 to 0.44, so this is the cheapest next gain.
2. **Train a seq2point CNN** on the same splits and metrics, to see whether the extra complexity pays off.
3. **Use more homes for leave-one-house-out.** All 18 houses with a single washing machine would give a real spread of "new customer" results.
4. **Score at the event level** (matched, missed and invented washes), because utilities and customers think in washes, not minutes.
5. **Measure the coarse-data drop.** Re-run the model with the aggregate averaged to 15 and 30 minutes, to measure the drop discussed in Recommendation.md.
6. **Add per-appliance glitch limits**, and compare every house's raw channels with the official cleaned file month by month to find monitors that were moved.

## References

- Murray, D., Stankovic, L., Stankovic, V. (2017). An electrical load measurements dataset of United Kingdom households from a two-year longitudinal study. *Scientific Data* 4, 160122. Used for the sensor setup and known data issues.
- Murray, D., Liao, J., Stankovic, L., et al. (2015). A data management platform for personalised real-time energy feedback. *EEDAL 2015*. This is the citation requested by the dataset readme.
- Kelly, J., Knottenbelt, W. (2015). Neural NILM: deep neural networks applied to energy disaggregation. *ACM BuildSys '15*. Source of the 20 W on-threshold for washing machines, and of the idea of joining short off-periods and dropping short activations. The pause and minimum length here are adapted to 1-minute data and checked in RESULTS.md.
- Zhang, C., Zhong, M., Wang, Z., Goddard, N., Sutton, C. (2018). Sequence-to-point learning with neural networks for non-intrusive load monitoring. *AAAI-18*. Three ideas come from here:
  - predicting the appliance at one time point from a window of the aggregate (the rolling features are a tabular version of this);
  - MAE plus total-energy error as metrics;
  - testing on REFIT houses not seen in training.
- Makonin, S., Popowich, F. (2015). Nonintrusive load monitoring (NILM) performance evaluation. *Energy Efficiency* 8, 809-814. Explains why accuracy-style metrics mislead when an appliance is off most of the time, and why detection and energy estimation should be reported separately.
- Precioso, D., Gomez-Ullate, D. (2020). NILM as a regression versus classification problem: the importance of thresholding. arXiv:2010.16050. Shows that the on/off threshold applied to a regression output changes the classification scores, which is why the floor here is chosen on validation and not on test.
