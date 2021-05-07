# klipper_z_calibration

This is a Klipper plugin to self calibrate the nozzle offset to the print surface on a Voron V2.
There is no manual z offset calibration any more. It doesn't matte what nozzle or flex plate is used for the current print.

**No manual z offset calibration!**

## Requirements

- A z-endstop where the nozzle drives on a switch (the standard Voron V2 enstop)
- A magnetic switch bases probe on the print head ([like the one from Annex](https://github.com/Annex-Engineering/Annex-Engineering_Other_Printer_Mods/tree/master/VORON_Printers/VORON_V2dot4/Afterburner%2BMagnetic_Probe_X_Carriage_Dual_MGN9))
- The probe needs to be configured as normaly closed
- The `z_calibration.py` file copied to the `klipper/klippy/extras` folder

## What it does

1. After normal homing of the z axes, the z-endstop is used to probe the nozzle and the enclosure of the probe switch (near the trigger pin).
2. Then the probe is used to probe a point on the print surface.
3. With the first two probing points, the distance between probe and nozzle is determined.
4. The offset is calculated by subtracting this distance from the probed high on the print surface.
5. The calculated offset is applied by using the `SET_GCODE_OFFSET` command.

## How to configure it

The configuration looks like this:

```
{
[z_calibration]
switch_offset: 0.675 # D2F-5: about 0.5, SSG-5H: about 0.7
speed: 80
# this point is for probing the nozzle on the z-endstop
probe_nozzle_x: 206 
probe_nozzle_y: 300
# this point is for probing the switch on the z-endstop
probe_switch_x: 211
probe_switch_y: 281
# this point is for probing on the print surface
probe_bed_x: 150
probe_bed_y: 150
}
```

The `switch_offset` is the only needed offset in this calculation since the exact trigger point of the switch cannot be probed directly on a second switch. But, this value does not change and is specified by the switches datasheet.

## How to use it

The calibration is started by using the `CALIBRATE_Z` GCode. If the probe is not on the print head, it will abort the calibration. So, a macro can help here to unpark and park the probe like this:

```
{
[gcode_macro CALIBRATE_Z]
rename_existing: BASE_CALIBRATE_Z
gcode:
    CG28
    M117 Z-Calibration..
    _SET_LOWER_STEPPER_CURRENT
    _GET_PROBE
    BASE_CALIBRATE_Z
    _PARK_PROBE
    _RESET_STEPPER_CURRENT
    M117
}
```

Then the `CALIBRATE_Z` GCode needs to be added to the `PRINT_START` macro. For this, just replace the second z homing after QGL with this macro. The sequence could be like this:

1. home all axes
2. heat up the bed and nozzle
3. get probe, make QGL, park probe
4. clean the nozzle
5. CALIBRATE_Z
6. print intro line
7. start printing...

**!! Happy Printing with an always perfect first layer - doesn't matter what you just modded on your print head/bed or what nozzle and flex plate you like to use for the next print !!**