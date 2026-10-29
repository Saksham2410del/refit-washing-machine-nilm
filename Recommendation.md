# Recommendation: washing-machine estimates from smart-meter data

## What the model does and where to use it

From whole-home power at 1-minute resolution, the model estimates when the washing machine runs and how much it draws. On later months of five UK homes it finds washing-machine minutes with an F1 of 0.41 (0.17 for an hourly-average baseline), catches two thirds of heated washes and gets energy within 20% in four of five homes. On unseen homes F1 is 0.33.

- **Use it for:** approximate counts of heated washes and monthly washing energy across many homes, seeing when washing happens across a population, and choosing who gets washing-related advice.
- **Not for:**
  - billing or exact appliance kWh (it under-estimates heater power);
  - single events while other ~2 kW loads run;
  - washer-dryers;
  - 15/30-minute data, or non-UK homes, without retraining.

## Opportunity: cooler washes for households that wash hot

- **Heating is most of the energy.** 95% of the 2,019 washes heated their own water, and the heater used 76% of all washing-machine energy (66-83% per home).
- **It is visible from the meter alone.** The heater block is also what the model detects best, so heated washes can be counted per home without plug monitors.
- **Timing is a weaker lever.** Only 13.0% of washing energy falls in the 16:00-19:00 peak, about that window's 12.5% share of the day, so peak shifting would do little here.

**Action.** Send households with many heated washes a short message with their own numbers ("about 20 hot washes last month, 8 kWh, three quarters of it heating water"), and suggest 30 °C or eco programmes for everyday loads. With cold water entering at about 15 °C, a 30 °C wash needs roughly 40% less heating energy than a 40 °C wash (15 K of temperature rise instead of 25 K).

**Measuring it:**

- **Trial design.** Run a randomised trial with a message group and a control group.
- **Main outcome.** Heater energy per wash, estimated by the model, compared before vs after between the two groups (difference-in-differences). The random split balances the groups, and the before/after comparison removes seasonal effects.
- **Cross-checks.** Total household kWh from the meter (independent of the model), and heated-wash counts in a small sub-metered panel.
- **Practicalities.** Keep one model version throughout, run for at least 8 weeks, and size the groups for the smallest worthwhile change.

## Limitations

- **Overlapping signatures.** Kettles, dishwashers, tumble dryers and immersion heaters draw the same ~2 kW as the washing machine's heater. 17-47% of the model's false "on" minutes coincide with another metered heater, which runs in only 1-6% of minutes. Unmetered night-time water heating explains much of the rest.
- **Missing and bad data.**
  - The official cleaned files still miss 9-25% of minutes per home and hide outages as flat lines (11.7% of House 3).
  - Two of the five washing-machine monitors were faulty: House 5's got stuck, and House 11's went dead and is mis-calibrated.
  - Each gap also costs the following hour, because the model needs the last hour of the aggregate.
- **Household differences.** F1 falls from 0.41 to 0.33 on unseen homes, because the hour of day (the second most used feature) partly encodes each home's routine. House 5's washer-dryer started long, low-power programmes in 2015, and 72% of that energy was missed.

## Applying UK results in India

The model relies on the built-in heater that 95% of UK washes use. Many Indian homes have top-loading or semi-automatic machines that wash in cold water: a 340-410 W wash motor, a 140-240 W spin motor and 0.2-0.4 kWh per load, with no heater block. A wash then looks like a pump, a fan or an AC compressor.

The other big loads differ too. Geysers draw the same 2-3 kW as the UK heater, voltage swings change appliance power, and inverter batteries add hundreds of watts of recharging after power cuts. Indian smart meters also typically store 15- or 30-minute intervals. A UK model needs retraining on sub-metered Indian homes, probably with different features, before its numbers mean anything there.

## With only 15- or 30-minute data

At 1 minute, a heated wash is a 5-15 minute block of about 2 kW followed by an hour of motor activity and short spin peaks. The median wash peaks at 2,074 W as a 1-minute value, 1,124 W as its best 15-minute average and only 642 W as its best 30-minute average. That is the size of an ordinary evening half-hour for the whole house (509 W median, 1,576 W at the 90th percentile).

So it becomes hard to tell a wash from a kettle used twice or an oven, to know when it started more precisely than the interval, or to count back-to-back washes. Coarse data can still support monthly washing-energy estimates with context such as time of day, day of week and the home's usual pattern, but not reliable detection of single washes.

*Sources for the India figures:* [semi-automatic machine ratings](https://letsavelectricity.com/semi-automatic-washing-machine-power-consumption/); interval lengths from the [CEA smart meter specification](https://cea.nic.in/wp-content/uploads/notification/2024/01/Tech_Spec__Net_meter_for_solar_application__Static__Smart_meters_1Ph_3_Ph.pdf) (30 minutes) and the [ISGF white paper](https://indiasmartgrid.org/isgf/public/banner_img/1748423369UoTzV5NWCriaerfRnZUWgrXqfc3dsa890wslQdaZ.pdf) (15 minutes).
