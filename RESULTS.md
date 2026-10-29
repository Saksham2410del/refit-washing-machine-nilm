# Results

Numbers come from `src/eda_washing_machine.py` (Part 2) and `src/train_disaggregation.py` (Part 3), both run on the official cleaned REFIT files at 1-minute resolution. Every table also exists as a csv in `outputs/tables/`. All times are UK local time, after the timestamp fix described in DATA.md.

## Part 2: washing-machine EDA

### Homes and periods

Houses 1, 2, 3, 5 and 11, each over the full period of its cleaned file. That is September 2013 to July 2015, except House 11, which starts in June 2014. The washing-machine channel per house is in DATA.md.

### Availability and data quality

| House | WM channel | Period | Days | Missing | Frozen aggregate | Stuck WM monitor | Silent WM monitor | Issues: any / most |
|---|---|---|---|---|---|---|---|---|
| 1 | 5 | 2013-10-09 to 2015-07-10 | 639 | 12.6% | 0.06% | 0.03% | 2.0% | 1.8% / 0.5% |
| 2 | 2 | 2013-09-17 to 2015-05-28 | 617 | 24.6% | 0.57% | 0% | 0.4% | 1.5% / 0.1% |
| 3 | 6 | 2013-09-25 to 2015-06-02 | 615 | 11.4% | 11.7% | 0% | 0.4% | 6.9% / 4.6% |
| 5 | 3 | 2013-09-26 to 2015-07-06 | 648 | 9.3% | 0.27% | 2.2% | 0% | 7.6% / 4.8% |
| 11 | 3 | 2014-06-03 to 2015-06-30 | 392 | 11.0% | 0.71% | 0% | 12.4% | 1.7% / 0.7% |

All percentages are shares of minutes in the period. The checks behind these columns are explained in DATA.md:

- *Missing* means the minute has no reading at all.
- *Frozen aggregate* means the aggregate repeats exactly the same 1-minute value for 60+ minutes, a dead sensor that was forward-filled.
- *Stuck WM monitor* means the same check on the washing-machine channel, at 20 W or more.
- *Silent WM monitor* means 4+ weeks with no washing while the house is still measured; only minutes that had data are counted here.
- *Issues any / most* means at least one, or more than half, of the minute's readings carry the readme's Issues flag.

What stands out:

- **House 2 has the most missing data.** A quarter of its minutes have no readings.
- **House 3's aggregate clamp often stops while the monitors carry on.** There are 480 stretches of 1 to 38 hours in which the aggregate repeats one exact value (for example 1,528 W for 21 hours), while the washing-machine monitor keeps changing. That is 11.7% of the house's minutes.
- **House 5's washing-machine monitor got stuck 2.2% of the time.** In one case it held exactly 2,129 W for 13 hours, which would have counted as a single 28 kWh "wash".
- **House 11's monitor went silent for its last nine weeks**, from 26 April 2015, while the house was still being measured.
- **Few minutes are dropped for the Issues flag.** In every house under 5% of minutes are mostly flagged, and only those minutes are removed from the model data.

| House | WM at 0 W | WM off (< 20 W) | Cycles | Cycles per week | kWh per week |
|---|---|---|---|---|---|
| 1 | 97.5% | 98.1% | 373 | 4.8 | 1.76 |
| 2 | 94.3% | 95.3% | 322 | 4.9 | 3.07 |
| 3 | 92.9% | 94.2% | 573 | 8.5 | 4.90 |
| 5 | 53.4% | 94.4% | 676 | 8.3 | 3.74 |
| 11 | 91.6% | 98.4% | 75 | 1.8 | 1.22 |

Zero and off shares are out of valid minutes; cycles per week are out of weeks with valid data.

- **The machines are off almost all the time.** They draw under 20 W in 94-98% of minutes, which is why overall MAE says little in Part 3.
- **House 5's machine stays on standby.** It reads exactly 0 W in only 53% of minutes but under 20 W in 94%, so a display or standby circuit is on most of the time.
- **Washing frequency varies a lot.** It runs from 1.8 cycles a week in House 11 (one occupant) to about 8.5 in Houses 3 and 5. That is 63-255 kWh a year per home.

### How a cycle is detected

**The rule in plain language:**

- A wash starts when the machine draws at least 20 W. That is above its standby draw and the monitor noise.
- The machine often pauses while it soaks, drains or refills, and its power drops to a few watts. Pauses of up to 15 minutes count as part of the same wash.
- A wash ends when the machine stays below 20 W for more than 15 minutes.
- Anything shorter than 15 minutes, or using less than 0.05 kWh, is not a wash. These are door-lock blips, a programme selected and cancelled, or a short spin.

**Why a single threshold is not enough.** The table shows how many cycles the rule finds as the allowed pause changes.

| House | Raw on-periods | No pause joined | 5 min | 10 min | 15 min (used) | 30 min |
|---|---|---|---|---|---|---|
| 1 | 1,774 | 241 | 406 | 384 | 373 | 357 |
| 2 | 1,916 | 341 | 340 | 334 | 322 | 304 |
| 3 | 1,113 | 640 | 602 | 586 | 573 | 535 |
| 5 | 2,685 | 623 | 725 | 701 | 676 | 617 |
| 11 | 361 | 74 | 75 | 76 | 75 | 76 |

- **A plain threshold counts each wash several times.** "Raw on-periods" counts every stretch at or above 20 W, with nothing joined or filtered. It comes out at 2 to 6 times the final cycle count.
- **Joining nothing loses whole washes.** With no pauses joined, House 1 keeps only 241 of its 373 cycles. Its 33-minute washes break into pieces that are each shorter than 15 minutes, so the minimum-length filter throws them away.
- **The exact pause length matters little.** Between a 10-minute and a 30-minute pause, the count changes by at most 12% (House 5).
- **Why 15 minutes.** It covers soak and drain pauses, but stays below the time it takes to unload and reload for a second wash.

Kelly and Knottenbelt (2015) used 20 W, a 160-second minimum off-time and a 30-minute minimum on-time for washing machines at 6-second resolution. At 1-minute resolution, and with House 1's 33-minute programme, a longer pause and a shorter minimum fit better.

### Cycle characteristics across homes

| House | Cycles | Duration, min | Energy, kWh | 1-min peak, W | Heated | Heater share of energy | Needed a pause joined |
|---|---|---|---|---|---|---|---|
| 1 | 373 | 33 (32-36) | 0.32 (0.26-0.38) | 2,328 | 98.7% | 77.9% | 99.2% |
| 2 | 322 | 97 (89-107) | 0.62 (0.48-0.70) | 2,091 | 97.5% | 79.4% | 98.8% |
| 3 | 573 | 66 (62-71) | 0.55 (0.46-0.66) | 1,926 | 99.1% | 80.5% | 38.9% |
| 5 | 676 | 48 (36-79) | 0.30 (0.21-0.51) | 2,077 | 88.6% | 66.3% | 79.7% |
| 11 | 75 | 103 (54-115) | 0.52 (0.39-0.75) | 2,313 | 96.0% | 82.5% | 88.0% |
| All | 2,019 | 64 (37-87) | 0.45 (0.29-0.64) | 2,074 | 95.1% | 75.8% | 75.1% |

Values are medians, with the inter-quartile range in brackets. *Heated* means the cycle's 1-minute peak passes 1 kW. *Heater share* is the energy in minutes above 1 kW divided by the cycle's energy.

- **The water heater is most of a wash.** 95% of cycles heat their own water, and the heater accounts for 76% of all washing-machine energy (66-83% per home). This is the basis of the recommendation.
- **Homes run very different programmes.** House 1 almost always uses the same 33-minute programme (IQR 32-36 minutes). Houses 2 and 11 run programmes of about 1.5 hours. The median energy per cycle ranges from 0.30 to 0.62 kWh.
- **House 5 has the widest spread.** Its middle half of cycles runs 36-79 minutes, with a tail of evening events of 6-9.5 hours and 2-3.4 kWh. These fit wash-and-dry runs on its washer-dryer. Its heater share is the lowest (66%), because heat-pump drying draws under 1 kW.
- **House 3's machine rarely drops below 20 W mid-wash.** Only 39% of its cycles needed a pause joined, against 75-99% in the other homes.

### When people wash

| House | Cycle starts 16:00-19:00 | WM energy 16:00-19:00 | Cycles at weekends |
|---|---|---|---|
| 1 | 1.6% | 2.3% | 23.1% |
| 2 | 15.5% | 17.9% | 24.2% |
| 3 | 10.6% | 12.2% | 15.9% |
| 5 | 19.2% | 16.5% | 58.3% |
| 11 | 9.3% | 7.3% | 17.3% |
| All | 12.6% | 13.0% | 32.8% |

- **Most washing happens in the morning.** In every home the busiest start hours are between 08:00 and 13:00.
- **House 1 also washes before dawn.** 22.9% of its cycles start between 03:00 and 06:00. Its aggregate shows a steady night load of about 1.2 kW from about 01:00 to 06:00, which looks like water or storage heating on a night tariff, so this home already does a lot of its washing in the cheap window.
- **The evening peak gets about its fair share.** The 16:00-19:00 window takes 13.0% of washing-machine energy, close to the 12.5% of the day it covers, so washing is not concentrated in the peak. Houses 2 and 5 put the most there (17-18%) and House 1 almost none.
- **Day of week differs by household.** House 5 does 58.3% of its washes at the weekend (38.9% on Saturdays alone), while House 3 does 43% on Mondays and Tuesdays. Weekends are 28.6% of days.

### Plots

**(i) A typical washing day**

![24-hour trace](outputs/figures/eda_24h_trace.png)

The script picks a House 1 day with exactly one cycle of near-median energy and nearly complete data, so the day is typical rather than hand-picked. On Tuesday 1 April 2014 there is one 33-minute, 0.30 kWh cycle at about 11:55. Its heater block (about 2.3 kW) is far from the biggest thing that day:

- there is a 1.2 kW night load with 2-3.4 kW spikes between 01:00 and 06:00;
- two 10 kW blocks at about 10:10 and 22:45 are most likely an electric shower.

A model therefore cannot treat every 2 kW step as the washing machine. It needs the motor pattern that follows.

**(ii) Detected cycles up close**

![Zoomed cycles](outputs/figures/eda_cycle_zoom.png)

Yellow shading marks the heater (above 1 kW), the dashed line is the 20 W threshold, and blue shading is the detected cycle.

- **Top, House 1.** The heater runs for about 6 minutes at 2.3 kW. The drum then turns at 80-170 W with short stops, and the cycle ends with a spin ramping to about 480 W. Three on-periods were joined.
- **Bottom, House 2.** About 15 minutes of heating at 2.05 kW are followed by 70 minutes of drum movement at 30-280 W that dips under 20 W several times. Five on-periods were joined into one 93-minute, 0.63 kWh wash, which a plain 20 W threshold would have counted as five events.

**(iii) Cross-house comparison**

![Cross-house comparison](outputs/figures/eda_cross_house.png)

The figure shows energy per cycle and duration (boxplots), the share of cycle starts by hour of day (the grey band is 16:00-19:00), and the share by day of week.

- **The boxplots show how different the machines are.** House 1's cycles are short and tightly grouped, Houses 2 and 3 use more energy per wash, and House 5 spreads widely with a long tail of wash-and-dry runs.
- **Every home starts most washes in the late morning.** House 1 also has its pre-dawn block, and House 11 has a sharp 10:00-12:00 peak.
- **The day-of-week panel shows House 5's Saturday habit.**

## Part 3: disaggregation model

### Task and data

The model predicts the washing machine's 1-minute power from the household aggregate only, for Houses 1, 2, 3, 5 and 11. A minute is used for training and scoring when all of these hold:

- the aggregate and the washing machine both have a value;
- the aggregate is not frozen;
- the washing-machine monitor is not stuck or silent;
- no more than half of the minute's readings carry the Issues flag.

| House | Train | Validation | Test | Test minutes | Machine on in test |
|---|---|---|---|---|---|
| 1 | 2013-10-09 to 2014-12-31 | 2014-12-31 to 2015-03-26 | 2015-03-26 to 2015-07-10 | 116,988 | 1.97% |
| 2 | 2013-09-17 to 2014-12-23 | 2014-12-23 to 2015-03-03 | 2015-03-03 to 2015-05-28 | 99,098 | 4.98% |
| 3 | 2013-09-25 to 2014-12-23 | 2014-12-23 to 2015-03-08 | 2015-03-08 to 2015-06-02 | 97,672 | 5.74% |
| 5 | 2013-09-26 to 2014-12-22 | 2014-12-22 to 2015-03-17 | 2015-03-17 to 2015-07-06 | 118,242 | 7.96% |
| 11 | 2014-06-03 to 2015-01-19 | 2015-01-19 to 2015-03-04 | 2015-03-04 to 2015-04-26 | 63,828 | 1.18% |

That is 2.31 million training minutes, 0.50 million validation minutes and 0.50 million test minutes. House 11's data ends on 26 April 2015, when its washing-machine monitor goes silent.

### Features, model and baselines

- **Features (20, aggregate only).** The current value; the mean, min, max and standard deviation over the last 5, 15, 30 and 60 minutes; the 1-minute and 5-minute change; and the hour of day. All rolling windows look backwards only.
- **Model.** A LightGBM regressor with learning rate 0.05, 63 leaves, at least 100 rows per leaf, and up to 1,000 trees with early stopping on validation. Predictions are clipped at 0, and predictions below a floor (20, 50, 100, 200 or 300 W, whichever gives the best validation F1) are set to 0. Validation picked 20 W in five of the six fits and 50 W in one, and early stopping kept 148 to 405 trees.
- **Always-off baseline.** Predicts 0 W.
- **Hourly-profile baseline.** Predicts the average washing-machine power for each hour of the day, learned on the training period. It is per house in the chronological setup and pooled over the training houses in leave-one-house-out.

### Validation design

- **Chronological.** Per house, the first 70% of usable minutes go to training, the next 15% to validation and the last 15% to testing, in time order. One model is trained on all five houses.
- **Leave one house out.** Five models, each trained on four houses (their training and validation periods) and tested on the fifth house's test period.

There is no random split. A random split puts minutes from the same wash into both training and test, so the score would mostly measure memory. The features use only the aggregate, never the target, and only look back in time. The validation set is used only for early stopping and the output floor, and the test set is used once. Both setups are scored on the same test minutes.

### Metrics and why

| Metric | Why |
|---|---|
| MAE (W) | Standard error per minute. It is dominated by off minutes, so always-off already scores well on it. |
| MAE while running (W) | Error only where the true power is at least 20 W. It shows whether the model tracks the actual load. |
| Precision / recall / F1 (on at 20 W) | Whether the model knows *when* the machine runs, which matters for any advice about washing habits. |
| Energy error (%) | (predicted kWh - true kWh) / true kWh over the test period. It shows what a monthly bill breakdown would get right or wrong, and is the same idea as the signal aggregate error in Zhang et al. (2018). |

### Results

All five houses pooled, on the same test minutes for both setups:

| Setup | Method | MAE (W) | MAE while running (W) | Precision | Recall | F1 | Energy error |
|---|---|---|---|---|---|---|---|
| Chronological | Always off | 18.6 | 397 | 0 | 0 | 0 | -100% |
| Chronological | Hourly profile | 30.2 | 371 | 0.095 | 0.648 | 0.166 | -23% |
| Chronological | LightGBM | 21.2 | 300 | 0.324 | 0.553 | **0.409** | -31% |
| Leave one house out | Always off | 18.6 | 397 | 0 | 0 | 0 | -100% |
| Leave one house out | Hourly profile | 30.7 | 376 | 0.087 | 0.613 | 0.152 | -23% |
| Leave one house out | LightGBM | 24.6 | 346 | 0.254 | 0.454 | **0.325** | -35% |

LightGBM per house:

| House | F1, chronological | F1, unseen house | Energy error, chronological | Energy error, unseen house |
|---|---|---|---|---|
| 1 | 0.431 | 0.367 | -4% | -24% |
| 2 | 0.378 | 0.291 | -1% | -22% |
| 3 | 0.526 | 0.475 | -20% | -26% |
| 5 | 0.337 | 0.212 | -72% | -78% |
| 11 | 0.123 | 0.130 | +14% | +486% |

- **The model beats both baselines where it matters: when the machine runs and how much it draws.** F1 is 0.41, against 0.17 for the hourly profile and 0 for always-off. The error while the machine runs drops from about 400 W to 300 W.
- **Always-off has the lowest overall MAE (18.6 W).** The machine is off 95% of the time, so predicting nothing is nearly always right, and each false alarm costs the model more than its hits save. That is why overall MAE is reported but not used to judge the model.
- **A good energy total can hide a useless model.** The hourly profile gets the pooled total within 23% while knowing nothing about when washes happen, so a total-energy number alone does not show whether a model works.
- **The model under-estimates total energy (-31%), mostly because of House 5.** In the other four homes the energy error is between -20% and +14%. House 5's washer-dryer runs long, low-power wash-and-dry programmes in the test months that it rarely ran in 2014 (failure case 3).
- **New homes are harder.** F1 drops from 0.41 to 0.33 when the house is unseen, and the energy error widens. House 3 transfers best (0.53 to 0.48) and House 5 worst (0.34 to 0.21).
- **House 11 is the weakest result, partly for data reasons.** A single occupant washing about twice a week leaves the machine on in only 1.2% of test minutes, so even a small false-alarm rate swamps the real signal (precision 0.09). On top of that, two thirds of its heater minutes are removed by the Issues flag (see DATA.md), so its remaining washes have little of the heater left to find.

**What I tried and kept out.** Two quick side tests on the chronological split are not in the scripts:

- Adding forward-looking windows (the next 15, 30 and 60 minutes, as a seq2point-style model would see) raised F1 from 0.41 to 0.44 and lowered MAE from 21.2 to 19.3 W. That is a real but modest gain, so I kept the simpler backward-only model and list it as a next step.
- Features measuring the load above the house's 60-minute minimum made no difference (F1 0.40).

### Actual vs predicted on test data

![Actual vs predicted](outputs/figures/model_actual_vs_pred.png)

For each house the plot shows the test-period cycle with median energy, so the picture is not cherry-picked. Grey is the aggregate the model sees, blue the measured washing machine and orange the prediction. Gaps in the orange line are minutes excluded from scoring.

- **Timing is mostly right.** In every house the prediction rises and falls with the real cycle, including the low motor phase after the heater.
- **The heater's power is usually under-estimated.** House 2 is tracked best, at 1.0-1.7 kW predicted against a 2.1 kW block. In Houses 1, 3 and 5 the prediction stays under about 1 kW, because other 1-4 kW loads switch on and off around the same time and the model hedges.
- **A 10 kW load is not mistaken for the washing machine.** In House 2, a 10 kW block straight after the wash (most likely an electric shower) gets only 100-200 W of predicted washing-machine power.
- **House 11's panel is a fragment.** Its 2.3 kW heater block is excluded from scoring, because the monitor reads more than the whole-house aggregate there. Only the motor phase after it is scored, and the model misses most of that.

### What the model relies on

![Feature importance](outputs/figures/model_feature_importance.png)

- **The current aggregate is the strongest single feature** (21% of the total split gain).
- **The rolling minimums come next** (min_60 8.7%, min_30 7.8%, min_15 5.4%, min_5 3.9%; 26% together). They describe the house's base-load floor, so the model effectively asks how far the current load sits above that floor.
- **The hour of day is second** (8.9%). The model partly learns each home's routine, which helps on later months of a known home but not on a new one, and is one reason F1 drops in leave-one-house-out.
- **The 1-minute change matters little** (2.3%). At 1-minute resolution the heater's on/off step is often split across two minutes, so the level features carry more.

### Failure cases

1. **Other ~2 kW heating loads.** A washing machine's heater looks like a kettle, a dishwasher's heating phase, a tumble dryer or (in House 1) the separate washer-dryer.

   | House | False "on" minutes | False kWh | Another metered heater above 500 W during false "on" | Same, over all test minutes |
   |---|---|---|---|---|
   | 1 | 5,354 | 10.5 | 23.0% | 3.2% |
   | 2 | 6,722 | 20.0 | 33.8% | 3.8% |
   | 3 | 8,027 | 18.9 | 46.8% | 6.0% |
   | 5 | 4,847 | 8.0 | 25.5% | 1.8% |
   | 11 | 1,600 | 2.2 | 16.6% | 1.1% |

   The other heaters run in only 1-6% of test minutes, but they are on during 17-47% of the false "on" minutes, about 7-15 times more often than chance. Unmetered loads (water heating, an oven, a shower) explain much of the rest, and the figure below shows one of them.

   ![Failure case](outputs/figures/model_failure_case.png)

   The script picks the 6 test hours where the model invents the most washing-machine energy. Here that is House 2 on Saturday 28 March 2015, 02:25-08:25:

   - the aggregate sits at a steady 2.3-2.4 kW all night, an unmetered load that is probably water or storage heating on a night tariff;
   - kettle boils at about 06:30, 07:10 and 08:20 sit on top of it;
   - the model predicts up to about 1.2 kW of washing machine around 02:30-03:15 and again after 06:30, although the machine never ran.

   A constant 2.3 kW block is close enough to a heater phase to fool backward-looking statistics.

2. **Cold washes and drying.** Without the heater block, a wash is a few hundred watts of motor activity, which looks like many other loads. A test cycle counts as caught when at least half of its minutes are predicted on:

   - 67.1% of the 255 heated test cycles are caught (100% in House 1 and 96% in House 3);
   - only 10.0% of the 30 unheated ones are caught.

3. **Behaviour that changes over time, and new homes.** House 5's washer-dryer was "on" in 3.8% of training minutes but 8.0% of test minutes. From February to May 2015 the household started running long evening wash-and-dry programmes (6-9 hours, mostly under 1 kW) that hardly appear in 2014. The model catches only 31% of House 5's heated test cycles and misses 72% of its energy.

   The same problem is bigger for new customers. Without the house's own history, F1 falls by 0.05 to 0.13 in four of the five homes (House 11 stays at 0.12-0.13), because the model has to rely on what other machines and households look like.

### Interpretation

The model is good enough to say *roughly when* a home washes and *roughly how much* energy its washing machine uses per month in most homes. On later months it finds two thirds of heated washes and gets the energy within 20% in four of five homes.

It is not good enough for minute-level power, for single events when other heaters run at the same time, or for washer-dryers. For new homes it should be read as an estimate with a wide error band.

The heater is both the largest part of washing energy (76%) and what the model detects best. So the most useful insight it can support is about heated washes rather than exact timing, and that is the basis of Recommendation.md.
