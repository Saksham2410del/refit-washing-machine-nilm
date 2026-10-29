# REFIT washing machine disaggregation

This project cleans raw REFIT smart meter data, looks at how five UK homes use their washing machines, and estimates washing machine power from the whole-house reading at 1-minute resolution.

## What I built

There are three Python scripts. Together they run end to end, from the REFIT files to cleaned data, EDA, model predictions and evaluation.

1. `src/clean_house1.py` audits the raw House 1 data: timestamp parsing and ordering, duplicates, missing readings, irregular intervals and impossible values. It then cleans the data, resamples it to 1 minute, and plots it before and after cleaning.
2. `src/eda_washing_machine.py` analyses the washing machine channel in the official cleaned data for Houses 1, 2, 3, 5 and 11. It covers availability and data quality, a cycle detection rule, cycle statistics, and usage by hour of day and day of week.
3. `src/train_disaggregation.py` trains a LightGBM model that estimates washing machine power from the aggregate signal. It compares the model with two baselines, on a time split and on houses the model has never seen, and then looks at where it fails.

`src/common.py` holds the shared code: file loading, timestamp handling and the cycle rule. Figures and tables are saved to `outputs/`.

The write-ups are:

- [DATA.md](DATA.md): raw data and cleaning
- [RESULTS.md](RESULTS.md): EDA and model results
- [Recommendation.md](Recommendation.md): a one-page summary for a utility, plus the Section 4 answers

Main results:

- Raw House 1 has 8.5 million rows in two overlapping files. That includes 1.2 million duplicate timestamps, 3,276 impossible readings and 375 outages, the longest being 41.6 days. My cleaned 1-minute version matches the official cleaned file with a correlation of 0.991.
- The UNIX timestamps are not UTC everywhere. The raw files are in UK local time, and the official cleaned files switch from UTC to local time in October 2014. This showed up because my cleaned data and the official data were exactly one hour apart in summer 2014. `uk_time()` handles it.
- There are 2,019 washes across the five homes. A typical wash takes 64 minutes and uses 0.45 kWh, and 76% of that energy goes into heating water. Only 13% of washing energy falls in the 16:00-19:00 peak.
- On later months of the same homes the model's on/off F1 is 0.41. The hourly profile baseline gets 0.17 and always-off gets 0. On homes the model has never seen, F1 is 0.33.

## Data used

- Dataset: REFIT Electrical Load Measurements from the University of Strathclyde. It has 20 homes in the Loughborough area, recorded from October 2013 to July 2015. Each home has a clamp on the mains (the aggregate) and 9 plug monitors.
- Part 1 uses raw House 1: `RAW_House1_Part1.csv` and `RAW_House1_Part2.csv` from `REFIT_RAW_081116.7z`. They cover 9 October 2013 to 10 July 2015.
- Parts 2 and 3 use the official cleaned files `CLEAN_House1.csv`, `CLEAN_House2.csv`, `CLEAN_House3.csv`, `CLEAN_House5.csv` and `CLEAN_House11.csv`. They run from September 2013 to July 2015, except House 11, which starts in June 2014. The washing machine channel for each house comes from `CLEAN_READ_ME_081116.txt`.
- Sampling interval: about 8 seconds, because the logger polled every 6-8 s. I resample everything to 1-minute means.
- Units: active power in watts. Energy is in kWh, calculated as the sum of 1-minute watts divided by 60,000.
- Limitations:
  - outages, including about six weeks in early 2014;
  - sensors that are not synchronised;
  - monitors that got stuck, went silent or were moved;
  - timestamps that are not consistent;
  - House 5's machine is a washer-dryer.

  DATA.md has the details.

## Setup and run instructions

I used Python 3.13 on Windows, with pandas 3.0.5 and LightGBM 4.7.0. Python 3.11 or newer should work.

```
pip install -r requirements.txt
```

The data is not in the repo.

- Raw: download `REFIT_RAW_081116.7z` from the [REFIT dataset page](https://pureportal.strath.ac.uk/en/datasets/refit-electrical-load-measurements/). The portal has a browser check, so use a browser. Then extract `RAW_House1_Part1.csv` and `RAW_House1_Part2.csv` with 7-Zip.
- Cleaned: get `CLEAN_House1/2/3/5/11.csv`. You can take them from the creators' [Zenodo upload](https://doi.org/10.5281/zenodo.5063428), which has one file per house with MD5 checksums, or from `CLEAN_REFIT_081116.7z`. The Zenodo copy only has Houses 1-5 and 11, which is why I picked these five.

Put the files in `data/raw/` and `data/clean/`. Subfolders are fine. If you keep them somewhere else, pass `--data-dir`:

```
python src/clean_house1.py --data-dir C:/refit_data
python src/eda_washing_machine.py --data-dir C:/refit_data
python src/train_disaggregation.py --data-dir C:/refit_data
```

Each script prints its numbers and saves its figures and tables to `outputs/`. The three take about 3 minutes in total on my laptop, and they give the same numbers on every run.

## Preprocessing decisions

Timestamps: raw UNIX values are read as UK local time. Cleaned values are read as UTC before 1 October 2014 and as local time after that. The hour that repeats when the clocks go back is dropped. The evidence is in DATA.md.

Cleaning the raw House 1 data (Part 1):

1. Sort by time and average rows that share a timestamp. Most of them are exact copies.
2. Set these to missing:
   - negative values;
   - an aggregate above 25 kW, since a 100 A main fuse tops out at about 23 kW;
   - a plug monitor above 4 kW, since 13 A sockets top out at about 3.1 kW (this is also the official cleaning's cut-off);
   - an aggregate of exactly 0 W, because Part1 uses 0 to mean "sensor not available".
3. Resample to 1-minute means.
4. Forward fill gaps of up to 5 minutes. REFIT only logs when the load changes, so a short gap usually means nothing changed. Longer gaps stay missing and get an `is_outage` flag, so I'm not inventing data.

Extra checks on the cleaned files (Parts 2 and 3). A minute is dropped when:

- the aggregate is frozen on one exact value for an hour or more;
- the washing machine monitor is stuck on an "on" value;
- the monitor has been silent for 4 or more weeks;
- more than half of the minute's readings carry the readme's Issues flag.

Cycle rule: the machine counts as on at 20 W or more. On-periods with gaps of up to 15 minutes are joined, to cover soak and drain pauses. A cycle must last at least 15 minutes and use at least 0.05 kWh.

Model features: 20 features, all from the aggregate. They are:

- the current value;
- the mean, min, max and standard deviation over the last 5, 15, 30 and 60 minutes;
- the 1-minute and 5-minute change;
- the hour of day.

All windows look backwards only.

## Validation design

Model: LightGBM regression. I picked it because it trains in a minute or two on a laptop, needs no scaling, and its feature importances are easy to explain. Predictions below a floor are set to zero, because a regression model tends to predict small non-zero values when it's unsure. The floor is chosen on the validation set, and it came out at 20 W.

Baselines:

- always-off (0 W);
- an hourly profile, which is the average washing machine power for each hour of the day in the training period.

Splits: I didn't use a random split. Neighbouring minutes are nearly identical, so a random split would put almost the same rows into train and test and the score would mostly measure memory. I used two splits instead:

- Time split per house. The first 70% of each house's usable minutes is for training, the next 15% for validation (early stopping and the floor), and the last 15% for testing. One model is trained on all five houses. This answers: does it keep working on later months of a known home?
- Leave one house out. Train on four houses and test on the fifth house's test period. This answers: does it work for a new customer with no sub-metered history?

How this avoids leakage:

- the features use only the aggregate, never the washing machine signal;
- every window looks back in time, so no training row sees anything from the test period;
- the validation set is only used for early stopping and the floor;
- the test set is used once.

Both splits are scored on exactly the same test minutes.

Metrics:

- overall MAE;
- MAE only while the machine is really on (20 W or more), because that's when the power level matters;
- on/off precision, recall and F1 at 20 W, which tell you whether the model knows when the machine runs;
- the error in total energy (predicted vs true kWh), which is what a bill breakdown would show.

Overall MAE on its own is misleading here. The machine is off 94-98% of the time, so always-off gets the best MAE of the three methods.

## Assumptions

- The channel mapping in the readme is right for the whole period.
- The washing machine plug monitor is the ground truth. House 5's machine (AEG L99695HWD) is actually a washer-dryer, so its channel includes drying.
- All times are UK local time after the timestamp fix. Hour of day and day of week use local time, because that's the clock people live by.
- 1-minute averages are good enough for this task. "Peak power" means the highest 1-minute average.

## Trade-offs

- A tree model on window statistics is easy to train and explain. But it only sees the last hour as summaries, so it can't learn the full shape of a 90-minute cycle the way seq2point could.
- Backward-only windows can't leak and would work in real time. The cost is that the start of a cycle is harder to catch. In a quick side test that isn't in the scripts, adding forward windows raised F1 from 0.41 to 0.44.
- Forward filling short gaps matches how REFIT logs data, but it can hold a stale value for up to 5 minutes.
- Dropping frozen, stuck and flagged minutes gives cleaner labels, but the evaluation then skips some hard periods. For example, two thirds of House 11's heating minutes are dropped.
- Using one 4 kW limit for all plug monitors keeps things simple, but it lets through glitches that are too high for a fridge.
- Five houses is one more than the brief asks for, but it's still a small sample of new customers.

## Possible improvements

- Add forward-looking windows. This is the cheapest gain (see above).
- Try seq2point on the same splits and metrics.
- Use all 18 houses that have a single washing machine for the leave-one-house-out test.
- Score whole washes (found, missed and false) instead of minutes, because that's how a customer thinks about it.
- Rerun the model on 15- and 30-minute data to measure the drop.
- Add per-appliance glitch limits, and check the other houses for monitors that were moved.

## AI tools used

I used Claude as a coding assistant to help write and debug the pandas, LightGBM and matplotlib code, and to tidy the wording of these docs. The analysis design is mine: the cleaning rules, the gap thresholds, the cycle rule, the two validation splits and the metrics. Every number here comes from the scripts' output, and you can reproduce it with the commands above.

## References

- Murray, Stankovic and Stankovic (2017), An electrical load measurements dataset of United Kingdom households from a two-year longitudinal study, Scientific Data 4:160122. This is the dataset paper.
- Murray et al. (2015), A data management platform for personalised real-time energy feedback, EEDAL 2015. This is the citation the dataset readme asks for.
- Kelly and Knottenbelt (2015), Neural NILM: deep neural networks applied to energy disaggregation, BuildSys '15. I took the 20 W on-threshold for washing machines from here, along with the idea of joining short off-periods into one activation.
- Zhang et al. (2018), Sequence-to-point learning with neural networks for non-intrusive load monitoring, AAAI-18. My window features are a simple version of their window-to-point idea. I also took MAE plus energy error as metrics, and testing on REFIT houses that weren't used in training.
- Makonin and Popowich (2015), Nonintrusive load monitoring (NILM) performance evaluation, Energy Efficiency 8. This is why I report detection (F1) and energy separately, instead of an accuracy-type score that looks good when the appliance is mostly off.
- Precioso and Gomez-Ullate (2020), NILM as a regression versus classification problem: the importance of thresholding, arXiv:2010.16050. This is why the on/off floor is picked on validation rather than on test.
