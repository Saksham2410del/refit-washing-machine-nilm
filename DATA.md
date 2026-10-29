# Data

## Raw-data coverage

REFIT comes from the University of Strathclyde. It covers 20 homes around Loughborough between October 2013 and July 2015. Each home has a current clamp on the mains (the aggregate) and 9 plug monitors. Only active power is recorded, in watts, and the logger polled the sensors every 6-8 seconds.

Two things in the readme matter a lot for cleaning:

- A sensor only logs a value when its load changes, and the logger fills in the values in between.
- The 10 sensors are not synchronised with each other.

For Part 1 I used raw House 1 from `REFIT_RAW_081116.7z`. It comes as two files from two versions of the logging database:

| File | Rows | Period (UK time) | Unavailable sensor written as |
|---|---|---|---|
| `RAW_House1_Part1.csv` | 4,377,877 | 9 Oct 2013 14:06 to 1 Oct 2014 01:27 | 0 |
| `RAW_House1_Part2.csv` | 4,140,886 | 27 Jun 2014 21:57 to 10 Jul 2015 11:56 | NaN |

The two files overlap for 95 days. Part2 often writes each sensor's update as its own row, so 59% of its rows have some sensors blank. The columns are DATETIME, UNIX, Aggregate and Appliance1-9. House 1's washing machine is Appliance5, its fridge is Appliance1, and the other channels are listed in the readme.

For Parts 2 and 3 I used the official cleaned files for Houses 1, 2, 3, 5 and 11. I took them from the creators' Zenodo upload (DOI 10.5281/zenodo.5063428) and checked each one against its MD5 sum.

| House | Washing machine | Channel | Other heating appliances (channel) | Period |
|---|---|---|---|---|
| 1 | Beko WMC6140 | 5 | washer dryer (4), dishwasher (6), heater (9) | 2013-10-09 to 2015-07-10 |
| 2 | LG F1289TD | 2 | dishwasher (3), kettle (8) | 2013-09-17 to 2015-05-28 |
| 3 | not given | 6 | tumble dryer (4), dishwasher (5), kettle (9) | 2013-09-25 to 2015-06-02 |
| 5 | AEG L99695HWD | 3 | tumble dryer (2), dishwasher (4), kettle (8) | 2013-09-26 to 2015-07-06 |
| 11 | not given | 3 | dishwasher (4), kettle (7) | 2014-06-03 to 2015-06-30 |

Some notes on the houses:

- House 5's AEG is a heat-pump washer-dryer, so its channel includes drying as well as washing. I kept it because the readme lists it as a washing machine.
- I left out House 4, which has two washing machines.
- House 7 isn't in the Zenodo upload.

Energy in kWh is the sum of the 1-minute watts divided by 60,000.

## Quality findings

These numbers come from `python src/clean_house1.py`. They are also saved in `outputs/tables/house1_audit.csv`.

| Check | Result |
|---|---|
| Timestamps that don't parse (UNIX / DATETIME) | 0 / 0 |
| Rows out of order | 2 |
| Duplicate timestamps | 1,211,048 (884,707 identical, 326,341 with different values) |
| Sampling interval | median 7 s; 53% between 6 and 10 s, 32% under 6 s |
| Gaps between readings | 4,040 over 1 min, 390 over 5 min, 21 over 1 h, 12 over 1 day |
| Longest gap | 24 Jan to 6 Mar 2014 (41.6 days) |
| Aggregate blank / exactly 0 W | 188,973 / 12 |
| Negative values | 0 |
| Aggregate over 25 kW | 3 (max 29,159 W) |
| Plug monitor over 4 kW | 3,273 (max 98,301 W) |

### Timestamp parsing and ordering

Every row parses. The DATETIME text matches UNIX to within a second on every row. The two rows out of order are the start of Part2, which begins 95 days before Part1 ends, and the October 2013 clock change.

The bigger finding is that UNIX isn't UTC, even though the readme says it is. In the raw files:

- UNIX jumps forward exactly one hour at the spring clock changes: 3,605 s on 30 March 2014 and 3,607 s on 29 March 2015.
- It steps back 3,597 s at the October 2013 change.

That only happens if the values are UK local time.

The cleaned files are different again. Up to the end of September 2014 their UNIX values are UTC, and after that they are local time. This shows up when you line up raw and clean week by week:

- In summer 2014 the clean data is exactly one hour behind the raw data. That holds for 24-25 summer weeks in each house, and for 15 weeks in House 11, which only starts in June.
- From October 2014 onwards the two match.

The switch is where the first logging database (Part1) ends, so it looks like the official cleaning converted Part1 to UTC but not Part2.

`uk_time()` in `common.py` handles both cases. The hour that repeats when the clocks go back can't be placed, so I drop it (2,185 raw rows).

Two results show the fix works:

- My cleaned House 1 now lines up with the official one with no time offset in 21 of 22 months; February 2014 is mostly outage. The aggregate correlation between them went from 0.77 to 0.991.
- The model's F1 went from 0.395 to 0.409, because the hour-of-day feature now means the same thing in training and testing.

### Duplicate timestamps

Most duplicates are repeated rows inside Part1: 1,004,404 of them, mostly exact copies. Part2 adds 14,755, and the two files share 191,889 timestamps where they overlap.

Many of the duplicates with different values are Part2 rows that each carry a different sensor, so averaging them just merges them into one reading. I checked that Part1 and Part2 use the same clock in the overlap, so averaging across the two files is safe.

### Missing readings and irregular intervals

The intervals under 6 seconds come from two things: Part2's one-sensor rows, and the two files interleaving during the overlap.

The long gaps are outages:

- The 41.6-day gap is the February 2014 outage mentioned in the readme.
- The next longest are 8.6, 7.5, 4.4 and 2.3 days, all in 2015.

The blank readings have known causes:

- A blank aggregate is a Part2 row without the clamp reading.
- The electric heater monitor (Appliance9) is blank in 22% of rows.

### Impossible or extreme values

The readings over the limits are logger glitches, not real power. The same impossible values keep turning up on different plug monitors: 98,301, 73,725 and 65,535 (which is 2^16-1). None of these monitors can physically go above about 3 kW. The washer dryer channel has the most of them, at 2,085.

The 12 zero aggregate readings are in Part1, where 0 means "not available". There are no negative values.

## Cleaning steps

1. Read UNIX as UK local time. Drop rows that don't parse or that fall in the repeated autumn hour.
2. Sort by time. When rows share a timestamp, average them, ignoring blanks. Most are exact copies, so this rule only matters for the rows whose values differ.
3. Set to missing: negative values, an aggregate over 25 kW, a plug monitor over 4 kW, and an aggregate of exactly 0 W.
4. Resample to 1-minute means. That's about 9 readings per minute.
5. Forward fill gaps of up to 5 minutes. Longer gaps stay missing and get `is_outage = True`. A separate flag, `is_filled`, marks the minutes that were filled.

The output is `outputs/house1_clean_1min.parquet`, with 920,031 minutes (git-ignored).

## Decisions about gaps and outliers

- Limits:
  - 25 kW for the aggregate, because a house on a 100 A main fuse can't really draw more than about 23 kW.
  - 4 kW for plug monitors, because they sit on 13 A sockets that max out at about 3.1 kW. It is also the cut-off the official cleaning used.
- Bad values become missing, not 0. That way the minute average uses the other readings in that minute, and it doesn't pretend the appliance was off.
- Short gaps are forward filled, not interpolated. REFIT only logs changes, so a short gap usually means nothing changed, and interpolation would invent ramps.
- 5 minutes is shorter than the washing machine's heater phase, so a filled gap can't hide a whole phase.
- Each gap is measured before filling. pandas' `ffill(limit=5)` would also fill the first 5 minutes of a 41-day outage.
- Longer gaps are flagged, not filled. Filling them would invent usage (or non-usage), and the flag lets later steps skip them.

## Result of cleaning

- 920,031 minutes (639 days).
- 3,276 values removed.
- 853 minutes filled.
- 114,398 minutes (12.4%) marked as outage, across 375 outages. 21 of them are over an hour, and the longest is 41.6 days.

About 12.5% of minutes are still missing per channel. The exception is the electric heater monitor, at 23%.

![House 1 raw vs cleaned](outputs/figures/house1_before_after.png)

This compares raw 8-second readings (left) with the cleaned 1-minute data (right) for the aggregate, the fridge and the washing machine. It covers 25-26 March 2014. The script picks a 12-hour window that has removed glitches and a wash in it.

- The fridge monitor's 8,200 W and 4,100 W glitches are gone after cleaning.
- One 2,100 W fridge reading is under the 4 kW limit, so it gets through as a 1,320 W spike.
- The aggregate shows the house's night heating: a steady 1.2 kW from midnight, with 3.4 kW spikes.
- The wash at 05:15 looks the same before and after.

![House 1 daily coverage](outputs/figures/house1_coverage.png)

This is the daily coverage after cleaning. The big white gap is the February 2014 outage. Spring and early summer 2015 also have several outages that last a few days each.

Here is my cleaned data compared with the official `CLEAN_House1.csv`, minute by minute, wherever both have data:

| Channel | Minutes | MAE (W) | Within 10 W | Correlation |
|---|---|---|---|---|
| Aggregate | 803,498 | 9.1 | 93.6% | 0.991 |
| Fridge (1) | 802,320 | 0.4 | 99.3% | 0.992 |
| Washing machine (5) | 797,426 | 0.6 | 99.5% | 0.991 |
| Other 7 monitors | 707,436-803,508 | 0.0-0.4 | 98.9-99.9% | 0.973-0.999 |

So the simple pipeline ends up very close to the official one. The official file has values for only 155 of my 114,398 outage minutes, which means it leaves House 1's long outages empty instead of filling them.

## Checks on the cleaned data used in Parts 2 and 3

The readme says the official cleaning:

- corrected daylight saving (only partly, as shown above);
- moved monitor columns back after resets;
- forward filled NaNs;
- replaced monitor spikes over 4,000 W with 0;
- added an Issues column, which is 1 when the monitors add up to more than the aggregate.

The data still needed four more checks:

1. Frozen aggregate. The exact same 1-minute aggregate value for 60 minutes or more is treated as missing, because a real house never does that (the fridge alone changes it). House 3 has 480 of these, 1 to 38 hours long, for example 1,528 W for 21 hours. Meanwhile its plug monitors keep changing, so it's a dead clamp that got forward filled.
2. Stuck washing machine monitor. This is the same check on the washing machine channel at 20 W or more; long runs of zeros are normal. House 5's monitor once sat at exactly 2,129 W for 13 hours, which would have counted as one 28 kWh "wash".
3. Silent monitor. Four or more weeks with no washing at all, while the house is still being measured, is treated as unknown rather than off. House 11 had 4-11 washes a month and then nothing after 26 April 2015. In the other houses this rule only hits the February 2014 outage.
4. Issues flag. The sensors aren't in sync, so a single flagged reading shows up every time something switches on before the aggregate catches up, and those are exactly the heater's on/off minutes. So I only drop a minute when more than half of its readings are flagged.

| House | Missing | Frozen aggregate | Stuck monitor | Silent monitor | Issues (any / most) |
|---|---|---|---|---|---|
| 1 | 12.6% | 0.06% | 0.03% | 2.0% | 1.8% / 0.5% |
| 2 | 24.6% | 0.57% | 0% | 0.4% | 1.5% / 0.1% |
| 3 | 11.4% | 11.7% | 0% | 0.4% | 6.9% / 4.6% |
| 5 | 9.3% | 0.27% | 2.2% | 0% | 7.6% / 4.8% |
| 11 | 11.0% | 0.71% | 0% | 12.4% | 1.7% / 0.7% |

The silent column only counts minutes that had data.

House 11 has one more problem. When its machine is heating (over 1 kW), the washing machine monitor reads more than the whole-house clamp in 60% of those minutes, for example 2.3 kW against 2.0 kW. That's impossible, so one of the two sensors is off. Two thirds of these minutes are mostly flagged and get dropped, which makes House 11 the least reliable house for the model. For comparison, only 1% of House 2's heating minutes and 8% of House 3's have this problem.

## Remaining concerns

- In the Part1 files, a plug monitor reading of 0 could mean "off" or "not available", and there's no way to tell which.
- A single 4 kW limit lets through glitches that are too big for some appliances, like the 2,100 W fridge reading. Per-appliance limits would catch more.
- The timestamp fix is checked in detail on House 1, and the switch date is checked on all five houses. It isn't checked on every raw channel of the other houses.
- The sensors aren't synced to the second, and House 11 also has a calibration mismatch. Smaller mismatches in other houses would be hard to see.
- Monitors may have been moved between appliances. For House 1, every channel matches the official file closely, but I haven't checked the other houses.
- Long outages are flagged, not filled, so any daily or monthly total that touches one is too low.
- House 5's drying runs count as washing machine use. From February 2015 it also started running long evening wash-and-dry programmes that barely appear in 2014.
- 8-second polling misses anything shorter, and the 1-minute averages smooth out the spin peaks.
- "Television Site" and "Computer Site" can be several devices on one monitor. They aren't used here.
