# This is a Klipper plugin for a self calibrating z offset

This is a Klipper plugin to self calibrate the nozzle offset to the print surface on a
Voron V1/V2. There is no need for a manual z offset or first layer calibration any more.
It is possible to change any variable in the printer from the temperature, the nozzle,
the flex plate, any modding on the print head or bed or even changing the z endstop
position value of the klipper configuration. Any of these changes or even all of them
together do **not** influence the first layer at all.

## Why this

- With the Voron V1/V2 z-endstop (the one where the tip of the nozzle clicks on a switch),
  you can exchange nozzles without changing the offset:
  ![endstop offset](pictures/endstop-offset.png)
- Or, by using a mag-probe (or SuperPinda, but this is not probing the surface directly)
  as a z-endstop, you can exchange the flex plates without changing the offset:
  ![probe offset](pictures/probe-offset.png)
- But you cannot get both or even more..

And this is what I did. I just combined these two probing methods to be completely
independent of any offset calibrations.

## Requirements

- A z-endstop where the tip of the nozzle drives on a switch (like the standard
  Voron V1/V2 enstop)
- A magnetic switch based probe at the print head - instead of the stock inductive probe
  ([e.g. this one from Annex](https://github.com/Annex-Engineering/Annex-Engineering_Other_Printer_Mods/tree/master/VORON_Printers/VORON_V2dot4/Afterburner%2BMagnetic_Probe_X_Carriage_Dual_MGN9))
- The `z_calibration.py` file needs to be copied to the `klipper/klippy/extras` folder.
  Klipper will then load this file if it finds the `z_calibration` configuration section.
- It's good practise to use the probe switch as normaly closed. Then, macros can detect
  if the probe is attached/released properly. The plugin is also able to detect that
  the mag-probe is attached to the print head - otherwise it will stop.
- (My previous Klipper macro for compensating the temperature based expansion of the
  z-endstop rod is **not** needed anymore.)

> **Note:** After copying the pyhton script, a full Klipper service restart is needed to
> load it!

## What it does

1. Normal homing of all axes using the z-endstop for z - now we have a zero point in z.
2. Determine the height in z of the nozzle by probing the tip of it on the z-endstop
   (should be mor or less the homed enstop position):
   ![nozzle position](pictures/nozzle-position.png)
3. Determine the height in z of the mag-probe by probing the body of the switch on the
   z-endstop:
   ![switch position](pictures/switch-position.png)
4. Calculate the offset between the tip of the nozzle and the trigger point of the
   mag-probe:

   `nozzle switch offset = mag probe z height - nozzle z height + switch offset`

   ![switch offset](pictures/switch-offset.png)
5. Determine the height in z of the print surface by probing one point with the mag-probe.
6. Calculate the final offset:

   `probe offset = probed z height - calculated nozzle switch offset`

7. Finally, the calculated offset is applied by using the `SET_GCODE_OFFSET` command
   (a previous offset is resetted before).

### Drawback

The only downside is, that the trigger point of the mag-probe cannot be probed directly.
This is why the body of the switch is clickt on the endstop. This small offset between the
body of the switch and the trigger point can be taken from the datasheet of the switch and
is not influenced in any way (at least I thought so).

### Interference

Temperature or humindity changes are not a problem since the switch is not influenced much
by them and all values are probed in a small time period and only the releations to each
other are used. The nozzle height in step 2 can be determined some time later and even
some celsius higher, compared to the homing in step 1. That is why the nozzle is probed
again and can vary to the first homing position.

### Example

The output of the calibration with all determined positions looks like this
(the offset is the one which is applied as GCode offset):

```
Z-CALIBRATION: ENDSTOP=-0.300 NOZZLE=-0.300 SWITCH=6.208 PROBE=7.013 --> OFFSET=-0.170
```

The endstop value is the homed z position which is the same as the configure
z-endstop position and here even the same as the second nozzle probe.

## How to configure it

The configuration of this plugin looks like this:

```
[z_calibration]
switch_offset:
#   The trigger point offset of the used switch of the
#   mag-probe. This needs to be determined manually.
#   More on this later in this section..
max_deviation: 1.0
#   The maximum allowed deviation of the calculated offset.
#   If the offset exceeds this value, it will stop!
#   The default is 1.0 mm.
speed: 100
#   The moving speed in X and Y. The default is 100
probe_nozzle_x:
probe_nozzle_y:
#   The X and Y coordinates for clicking the nozzle on the
#   z-endstop.
probe_switch_x:
probe_switch_y:
#   The X and Y coordinates for clicking the probe's switch
#   on the z-endstop.
probe_bed_x:
probe_bed_y:
#   The X and Y coordinates for probing on the print surface
#   (e.g. the center point)
```

The `switch_offset` is the already mentioned offset from the switch body (which is the
probed position) to the actual trigger point. The value can be taken from the datasheet of
the Omron switch (D2F-5: 0.5mm and SSG-5H: 0.7mm). It is good to start with a little less
depending on the squishiness you prefer for the first layer (for me, it's -0.25). This
value is a really fixed one!

For the move up commands after probing, the `z_offset` parameter of the `[probe]` section
is used and also doubled for clearance safety. Further on, from the z configuration, the
`(second_)homing_speed`, `homing_retract_dist` and `position_min` values are taken for
probing too.

It even doesn't matter what z-endstop position is configured in Klipper. All positions are
relative to this point - only the absolute values are different. But, it is advisable to
configure a safe value here to not crash the nozzle in the build plate by accident. The
plugin only changes the GCode Offset and it is still possible to move the nozzle over this
offset.

> **Note:** ~~With the recent Klipper version I recognized, that the switch is not clicking
> anymore while probing. May be, it is because of the fixed bug regarding the clock speed
> divider and the mcu is reacting faster now? Or there were any other changes in the
> probing routine, which I missed. And this is a change in the whole system, which direcly
> influences this switch offset. As a consequence, I had to increase the switch offset...~~
> My SSG-5H switch got damaged somehow and the repeatability got worse too. I'm not sure if
> this was my fault or if the switch is not the best choice..

## How to use it

The calibration is started by using the `CALIBRATE_Z` command. If the probe is not
attached to the print head, it will abort the calibration process. So, macros can help
here to unpark and park the probe like this:

```
[gcode_macro CALIBRATE_Z]
rename_existing: BASE_CALIBRATE_Z
gcode:
    CG28
    M117 Z-Calibration..
    _SET_LOWER_STEPPER_CURRENT  # I lower the stepper current for homing and probing 
    _GET_PROBE                  # a macro for fetching the probe first
    BASE_CALIBRATE_Z
    _PARK_PROBE                 # and parking it afterwards
    _RESET_STEPPER_CURRENT      # resetting the stepper current
    M117
```

Then the `CALIBRATE_Z` command needs to be added to the `PRINT_START` macro. For this,
just replace the second z homing after QGL with this macro. The sequence could look
like this:

1. home all axes
2. heat up the bed and nozzle (and chamber)
3. get probe, make QGL, park probe
4. clean the nozzle
5. get probe, CALIBRATE_Z, park probe
6. print intro line
7. start printing...

> Happy printing with an always perfect first layer - doesn't matter what you just
> modded on your print head/bed or what nozzle and flex plate you like to use for the next
> print. It just stays the same :-)

## Dislaimer

It works perfectly for me. But, at this moment it is not widely tested. And I don't know
much about the Klipper internals. So, I had to figure it out by myself and found this as a
working way for me. If there are better/easier ways to accomplish it, please don't
hesitate to contact me!
