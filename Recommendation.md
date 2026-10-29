# Recommendation

## Summary for a utility

The model takes whole-house power at 1-minute resolution and estimates when the washing machine runs and roughly how much it uses. I tested it on later months of five UK homes:

- On/off F1 is 0.41. An hourly average baseline gets 0.17.
- It catches two thirds of heated washes.
- It gets the energy total within 20% in four of the five homes.

On a home it hasn't seen before, F1 drops to 0.33.

### Suitable uses

- Approximate numbers across many homes: how many heated washes, roughly how much washing energy per month, and when people wash.
- Picking which customers should get washing-related advice. The heater block, which is most of a wash's energy, is the thing it detects best.
- Population-level patterns, where errors in individual homes average out.

### Limits of the model

- It isn't accurate enough for billing or exact appliance kWh. It usually underestimates heater power.
- It struggles with single washes while other ~2 kW loads are running, such as a kettle, a dishwasher or water heating.
- It's weak on washer-dryers, and on any machine that doesn't heat water (only 10% of unheated cycles are caught).
- It needs 1-minute data and UK-style machines. On 15/30-minute data or in other countries it would need retraining (see below).
- On new homes, expect the unseen-house numbers (F1 0.33), not the time-split ones.

## Answers to Section 4

### 1. Opportunity: target hot washes

I expected peak-time shifting to be the obvious opportunity, but the data doesn't really support it. Only 13.0% of washing energy falls between 16:00 and 19:00, which is about that window's share of the day (12.5%). One of the five homes already does a quarter of its washing at night.

Water heating is the bigger lever:

- 95% of the 2,019 washes heated their own water.
- The heater used 76% of all washing machine energy (66-83% per home).
- The heater is also what the model picks up best from the meter, so a utility could count heated washes per home without plug monitors.

So the idea is to send households with a lot of heated washes a short message with their own numbers. For example: "about 20 hot washes last month, about 8 kWh, three quarters of it heating water". The message would suggest 30 °C or eco programmes for normal loads.

As a rough size: with cold water coming in at about 15 °C, a 30 °C wash needs around 40% less heating energy than a 40 °C wash. That's 15 K of heating instead of 25 K.

How I'd measure whether it worked:

- Randomly split eligible customers into a message group and a control group.
- Main outcome: heater energy per wash, from the model. Compare the before/after change between the groups (difference-in-differences), so seasonal effects cancel out.
- Checks that don't depend on the model: total household kWh, and heated-wash counts on a small sub-metered panel.
- Run it for at least 8 weeks with one fixed model version, and size the groups for the smallest change worth acting on.

### 2. Limitations

Overlapping appliance signatures. Kettles, dishwashers, tumble dryers and immersion heaters all draw about 2 kW, like the heater. 17-47% of the model's false alarms happen while another metered heater is on, even though those are only on 1-6% of the time. Unmetered night-time water heating probably explains a lot of the rest.

Missing data. Even the official cleaned files miss 9-25% of minutes per home, and they hide some outages as flat lines (11.7% of House 3). Two of the five washing machine monitors were faulty: House 5's got stuck, and House 11's went dead and reads higher than the whole house. The model also needs the previous hour of data, so every gap costs the hour after it as well.

Household differences. F1 goes from 0.41 to 0.33 on an unseen home. Part of the reason is that hour of day, the second most important feature, learns each home's routine. Machines and habits also vary a lot: House 1 runs the same 33-minute programme every time, while House 5's washer-dryer started long, low-power runs in 2015, and 72% of that energy was missed.

Applying UK results to India. The model relies on the built-in water heater that shows up in 95% of UK washes. Many Indian homes use cold-water top-loading or semi-automatic machines instead:

- a 340-410 W wash motor and a 140-240 W spin motor;
- 0.2-0.4 kWh per load;
- no heater block at all.

To the model, that wash looks like a water pump, a fan or an AC compressor.

The big loads are different too:

- geysers draw the same 2-3 kW as the UK heater;
- ACs and pumps are common;
- voltage swings change appliance power;
- inverter batteries add hundreds of watts while recharging after power cuts.

Indian smart meters usually record 15- or 30-minute intervals as well. So a UK model would need retraining on sub-metered Indian homes, probably with different features.

### 3. If only 15- or 30-minute smart-meter data were available

At 1 minute, a heated wash is a clear 5-15 minute block of about 2 kW, followed by an hour of motor activity and short spin peaks. Coarser data flattens this out:

- The median wash peaks at 2,074 W as a 1-minute value.
- At 15 minutes, its best average is 1,124 W.
- At 30 minutes, it's only 642 W.
- For comparison, a normal evening half-hour for the whole house is 509 W (median) to 1,576 W (90th percentile).

So at 30 minutes a typical wash is about the size of ordinary evening use, and the motor and spin phases vanish. That makes it hard to tell a wash from a couple of kettle boils or the oven, to know when it started, or to separate back-to-back washes. Coarse data could still give monthly washing-energy estimates if the model gets extra context, such as time of day, day of week and the home's usual pattern, but it couldn't reliably detect individual washes.

Sources for the India figures: [semi-automatic machine ratings](https://letsavelectricity.com/semi-automatic-washing-machine-power-consumption/), the [CEA smart meter spec](https://cea.nic.in/wp-content/uploads/notification/2024/01/Tech_Spec__Net_meter_for_solar_application__Static__Smart_meters_1Ph_3_Ph.pdf) (30 minutes) and the [ISGF white paper](https://indiasmartgrid.org/isgf/public/banner_img/1748423369UoTzV5NWCriaerfRnZUWgrXqfc3dsa890wslQdaZ.pdf) (15 minutes).
