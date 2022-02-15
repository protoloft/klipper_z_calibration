# This is a Klipper plugin for a self calibrating Z offset

This is a Klipper plugin to self calibrate the nozzle offset to the print surface on a
Voron V1/V2. There is no need for a manual Z offset or first layer calibration any more.
It is possible to change any variable in the printer from the temperature, the nozzle,
the flex plate, any modding on the print head or bed or even changing the Z endstop
position value in the klipper configuration. Any of these changes or even all of them
together do **not** affect the first layer at all.

Here is a small video for a demonstration:
[https://streamable.com/wclrmc](https://streamable.com/wclrmc)

### Many thanks for all your feedback to make this happen

And, if you like my work and would like to support me, please feel free to donate here:

[![](https://www.paypalobjects.com/en_US/i/btn/btn_donate_LG.gif)](https://www.paypal.com/donate?hosted_button_id=L3ZN4SAWW2NMC)

# News

- **v0.8.0**
  - New configurations for executing G-Code commands (useful for V1 users)
  - Bugfix for configuring the z_calibration too early (many thanks to Frix-x),
  - New example configurations
  - **Action needed** for the Moonraker update, see: [Moonraker Updater](#moonraker-updater)
- **v0.7.0**
  - New "PROBE_Z_ACCURACY" command
  - Eenaming of the dummy service (**CAUTION**: the configuration needs to be adapted for this!)
  - Fix in "_SET_ACC" Macro
- **v0.6.2**
  - As desired, added Moonraker Update possibility.
- **v0.5**
  - Added compatibility for newer Klipper versions.
- **v0.4**
  - The "calibrate_z:probe_bed_x|y" settings can be omitted in the configuration and the
  "mesh:relative_reference_index" of the bed mesh is taken as default instead.
- **v0.3**
  - A new option to first probe down fast before recording the probing samples is added.
  - And all indirect properties from other sections can be customized now.
- **v0.2**
  - The probing repeatability is now increased dramatically by using the probing
    procedure instead of the homing procedure!

# Table of Content

>:pray: **Please:** read this document carefully! Any details from feedbacks and trouble
>shootings are documented here!

- [Why This](#why-this)
- [Requirements](#requirements)
- [What It Does](#what-it-does)
  - [Drawback](#drawback)
  - [Interference](#interference)
  - [Example](#example)
- [How To Install It](#how-to-install-it)
- [How To Configure It](#how-to-configure-it)
  - [Preconditions](#preconditions)
  - [Configurations](#configurations)
  - [Bed Mesh](#bed-mesh)
  - [Switch Offset](#switch-offset)
  - [Moonraker Updater](#moonraker-updater)
- [How To Test It](#how-to-test-it)
- [How To Use It](#how-to-use-it)
  - [Command CALIBRATE_Z](#command-calibrate_z)
  - [Command PROBE_Z_ACCURACY](#command-probe_z_accuracy)
- [Disclaimer](#disclaimer)

## Why This

- With the Voron V1/V2 Z endstop (the one where the tip of the nozzle clicks on a switch),
  you can exchange nozzles without adapting the offset:
  ![endstop offset](pictures/endstop-offset.png)
- Or, by using a mag-probe (or SuperPinda, but this is not probing the surface directly
  and thus needs an other offset which is not as constant as the one of a switch)
  configured as Z endstop, you can exchange the flex plates without adapting the offset:
  ![probe offset](pictures/probe-offset.png)
- But, why can't you get both of it? Or even more.. ?

And this is what I did. I just combined these two probing methods to be completely
independent of any offset calibrations - forever. This is so amazing! :tada:

## Requirements

- A Z endstop where the tip of the nozzle drives on a switch (like the standard
  Voron V1/V2 enstop). It will not work with the virtual pin of the probe as endstop!
- A magnetic switch based probe at the print head - instead of the stock inductive probe
  (e.g. [this ones from Annex](https://github.com/Annex-Engineering/Quickdraw_Probe),
  or the popular drop in replacement [KlickyProbe](https://github.com/jlas1/Klicky-Probe))
- Both, the Z endstop and mag-probe are configured properly and homing and QGL are working.
- The "z_calibration.py" file needs to be copied to the `klipper/klippy/extras` folder.
  Klipper will then load this file if it finds the "[z_calibration]" configuration section.
  It does not interfere with the Moonraker's Klipper update since git ignores unknown
  files.
- It's good practise to use the probe switch as normally closed. Then, macros can detect
  if the probe is attached/released properly. The plugin is also able to detect that
  the mag-probe is attached to the print head - otherwise it will stop!
- (My previous Klipper macro for compensating the temperature based expansion of the
  Z endstop rod is **not** needed anymore.)

>:point_up: **Note:** After copying the pyhton script, a full Klipper service restart is needed to
> load it!

## What It Does

1. A normal homing of all axes using the Z endstop for Z (this is not part of this plugin).
   Now we have a zero point in Z. Everything is in relation to this point now. So, a new
   homing would change everything, since the homing is not that precise. That is one point,
   why absolute values of the offset are not so relevant.
2. Determine the height of the nozzle by probing the tip of it on the Z endstop
   (this can be slightly different to the homed one):
   ![nozzle position](pictures/nozzle-position.png)
3. Determine the height of the mag-probe by probing the body of the switch on the
   z-endstop:
   ![switch position](pictures/switch-position.png)
4. Calculate the offset between the tip of the nozzle and the trigger point of the
   mag-probe:

   `nozzle switch offset = mag probe height - nozzle height + switch offset`

   ![switch offset](pictures/switch-offset.png)
5. Determine the height of the print surface by probing one point with the mag-probe.
6. Now, calculate the final offset:

   `probe offset = probed height - calculated nozzle switch offset`

7. Finally, the calculated offset is applied by using the `SET_GCODE_OFFSET` command
   (a previous offset is resetted before!).

### Drawback

The only downside is, that the trigger point of the mag-probe cannot be probed directly.
This is why the body of the switch is clicked on the endstop. This small offset between the
body of the switch and the trigger point can be taken from the datasheet of the switch and
is hardly ever influenced in any way. And, this is the perfect setting for fine tuning
the first layer.

### Interference

Temperature or humindity changes are not a big deal since the switch is not affected much
by them and all values are probed in a small time period and only the releations to each
other are used. The nozzle height in step 2 can be determined some time later and even
many celsius higher in the printer, compared to the homing in step 1. That is why the
nozzle is probed again and can vary a little to the first homing position.

### Example

The output of the calibration with all determined positions looks like this
(the offset is the one which is applied as GCode offset):

```
Z-CALIBRATION: ENDSTOP=-0.300 NOZZLE=-0.300 SWITCH=6.208 PROBE=7.013 --> OFFSET=-0.170
```

The endstop value is the homed Z position which is always zero or the configure
"stepper_z:position_endstop" setting - and in this case, it's even the same as the
probed nozzle hight.

## How To Install It

To install this plugin, you need to copy the `z_calibration.py` file into the `extras`
folder of klipper. Like:
> klipper/klippy/extras/z_calibration.py

An alternative would be to clone this repo and run the `install.sh` script (more on
this in the [Moonraker Updater](#moonraker-updater) section).

## How To Configure It

### Preconditions

As a precondition, the probe needs to be configured properly. It is good to use more than
one sample and use "median" as "probe:samples_result". And it is **important** to configure
an appropriate probe offset in X, Y and **Z**. The Z offset does not need to be an exact
value, since we do not use it as an offset, but it needs to be roughly a real value!

It even doesn't matter what "stepper_z:position_endstop" value is configured in Klipper.
All positions are relative to this point - only the absolute values are different. But,
it is advisable to configure a safe value here to not crash the nozzle into the build
plate by accident. The plugin only changes the GCode offset and it's still possible to
move the nozzle beyond this offset.

### Configurations

The following configuration is needed to activate the plugin and to set some needed values:

>:bulb: **NEW:** If the nozzle cannot be probed with the mag-probe attached (Voron V1), then
> it's now possible to detach (start_gcode), attach before probing the switch (before_switch_gcode)
> and even detaching it at the end (end_gcode).

```
[z_calibration]
probe_nozzle_x:
probe_nozzle_y:
#   The X and Y coordinates (in mm) for clicking the nozzle on the
#   Z endstop.
probe_switch_x:
probe_switch_y:
#   The X and Y coordinates (in mm) for clicking the probe's switch
#   on the Z endstop.
probe_bed_x: default from relative_reference_index of bed_mesh
probe_bed_y: default from relative_reference_index of bed_mesh
#   The X and Y coordinates (in mm) for probing on the print surface
#   (e.g. the center point) These coordinates will be adapted by the
#   probe's X and Y offsets. The default is the relative_reference_index
#   of the configured bed_mesh. It will raise an error if there is no
#   probe_bed site and no bed_mesh with a relative_reference_index
#   configured.
switch_offset:
#   The trigger point offset of the used mag-probe switch.
#   This needs to be fined out manually. More on this later
#   in this section..
max_deviation: 1.0
#   The maximum allowed deviation of the calculated offset.
#   If the offset exceeds this value, it will stop!
#   The default is 1.0 mm.
samples: default from "probe:samples" section
#   The number of times to probe each point. The probed z-values
#   will be averaged. The default is from the probe's configuration.
samples_tolerance: default from "probe:samples_tolerance" section
#   The maximum Z distance (in mm) that a sample may differ from other
#   samples. The default is from the probe's configuration.
samples_tolerance_retries: default from "probe:samples_tolerance_retries" section
#   The number of times to retry if a sample is found that exceeds
#   samples_tolerance. The default is from the probe's configuration.
samples_result: default from "probe:samples_result" section
#   The calculation method when sampling more than once - either
#   "median" or "average". The default is from the probe's configuration.
clearance: 2 * z_offset from the "probe:z_offset" section
#   The distance in mm to move up before moving to the next
#   position. The default is two times the z_offset from the probe's
#   configuration.
position_min: default from "stepper_z:position_min" section.
#   Minimum valid distance (in mm) used for probing move. The
#   default is from the Z rail configuration.
speed: 50
#   The moving speed in X and Y. The default is 50 mm/s.
lift_speed: default from "probe:lift_speed" section
#   Speed (in mm/s) of the Z axis when lifting the probe between
#   samples and clearance moves. The default is from the probe's
#   configuration.
probing_speed: default from "stepper_z:homing_speed" section.
#   The fast probing speed (in mm/s) used, when probing_first_fast
#   is activated. The default is from the Z rail configuration.
probing_second_speed: default from "stepper_z:second_homing_speed" section.
#   The slower speed (in mm/s) for probing the recorded samples.
#   The default is second_homing_speed of the Z rail configuration.
probing_retract_dist: default from "stepper_z:homing_retract_dist" section.
#   Distance to backoff (in mm) before probing the next sample.
#   The default is homing_retract_dist from the Z rail configuration.
probing_first_fast: false
#   If true, the first probing is done faster by the probing speed.
#   This is to get faster down and the result is not recorded as a
#   probing sample. The default is false.
start_gcode:
#   A list of G-Code commands to execute prior to each calibration command.
#   See docs/Command_Templates.md for G-Code format. This can be used to
#   attach the probe.
before_switch_gcode:
#   A list of G-Code commands to execute prior to each probing on the
#   mag-probe. See docs/Command_Templates.md for G-Code format. This can be
#   used to attach the probe after probing on the nozzle and before probing
#   on the mag-probe.
end_gcode:
#   A list of G-Code commands to execute after each calibration command.
#   See docs/Command_Templates.md for G-Code format. This can be used to
#   detach the probe afterwards.
```

>:bulb: **INFO:** The settings about probing from this section do not apply to the probing on the
>bed, since the script just calls the probe to do it's job at this point. Only the first fast down
>probing is covered by this script directly.

### Bed Mesh

If you use a bed mesh, the coordinates for probing on the print bed must be exactly the
relative reference point of the mesh since this is the zero point! But, you can ommit
these properties completely now and the relative reference point of the mesh will be
taken automatically (for this, the "bed_mesh:relative_reference_index" setting is required
and there is no support for round bed/mesh so far)!

### Switch Offset

The "z_calibration:switch_offset" is the already mentioned offset from the switch body
(which is the probed position) to the actual trigger point above it. A starting point
for this value can be taken from the datasheet of the Omron switch (D2F-5: 0.5mm and SSG-5H: 0.7mm).
It's safe to start with a little less depending on the squishiness you prefer for the
first layer (for me, it's about 0.46 for the D2F-5). So, with a smaller offset value, the nozzle
is more away from the bed! The value cannot be negative.

For example, the datasheet of the D2F-5:

![endstop offset](pictures/d2f-example.png)

And the calculation of the offset base:

```
offset base = OP (Operation Position) - switch body height
     0.5 mm = 5.5 mm - 5 mm
```

### Moonraker Updater

>:point_up: **Attention:** If this was already configure prior to version 0.8,
> a manual execution of the "install.sh" script is needed to update the soft link and
> the dummy service definition like: `/home/pi/klipper_z_calibration/install.sh`!

Now, a update with the Moonraker update manager is possible by adding this configuration
block to the "moonraker.conf":

```
[update_manager client z_calibration]
type: git_repo
path: /home/pi/klipper_z_calibration
origin: https://github.com/protoloft/klipper_z_calibration.git
install_script: install.sh
```

For this, you need to clone this repository in your home directory (/home/pi):

```
git clone https://github.com/protoloft/klipper_z_calibration.git
```

The script assumes that Klipper is also in your home directory under
"klipper": `${HOME}/klipper`.

>:point_up: **NOTE:** Currently, there is a dummy systemd service installed
> to satisfy moonraker's update manager which also restarts Klipper after an
> update.

## How To Test It

Do not bother too much about absolute values of the calculated offsets. These can vary a lot.
Only the real position from the nozzle to the bed counts. To test this, the result of the
calibration can be queried by `GET_POSITION` first:

```
> CALIBRATE_Z
> Z-CALIBRATION: ENDSTOP=-0.300 NOZZLE=-0.267 SWITCH=2.370 PROBE=3.093 --> OFFSET=-0.010000
> GET_POSITION
> mcu: stepper_x:17085 stepper_y:15625 stepper_z:-51454 stepper_z1:-51454 stepper_z2:-51454 stepper_z3:-51454
> stepper: stepper_x:552.500000 stepper_y:-47.500000 stepper_z:10.022500 stepper_z1:10.022500 stepper_z2:10.022500 stepper_z3:10.022500
> kinematic: X:252.500000 Y:300.000000 Z:10.022500
> toolhead: X:252.500000 Y:300.000000 Z:10.021472 E:0.000000
> gcode: X:252.500000 Y:300.000000 Z:9.990000 E:0.000000
> gcode base: X:0.000000 Y:0.000000 Z:-0.010000 E:0.000000
> gcode homing: X:0.000000 Y:0.000000 Z:-0.010000
```

Here, the Z position in "gcode base" reflects the calibrated Z offset.

Then, the offset can be tested by moving the nozzle slowly down to zero by moving it in
multiple steps. It's good to do this by using GCodes, since the offset is applied as
GCode-Offset. For example like this:

```
> G90
> G0 Z5
> G0 Z3
> G0 Z1
> G0 Z0.5
> G0 Z0.3
> G0 Z0.1
```

Check the distance to the print surface after every step. If there is a small discrepancy
(which should be smaller than the offset base from the switch's datasheet), then adapt
the "z_calibration:switch_offset" by that value. Decreasing the "switch_offset" will move
the nozzle more away from the bed.

And finally, if you have double checked, that the calibrated offset is correct, you can go
for fine tuning the "z_calibration:switch_offset" by actually printing first layer tests.

## How To Use It

### Command CALIBRATE_Z

The calibration is started by using the `CALIBRATE_Z` command. There are no more parameters.
If the probe is not attached to the print head, it will abort the calibration process
(if configured normaly closed). So, macros can help here to attach and detach the probe like
this:

```
[gcode_macro CALIBRATE_Z]
rename_existing: BASE_CALIBRATE_Z
gcode:
    CG28
    M117 Z-Calibration..
    _SET_LOWER_STEPPER_CURRENT  # I lower the stepper current for homing and probing 
    ATTACH_PROBE                # a macro for fetching the probe first
    BASE_CALIBRATE_Z
    DETACH_PROBE                # and parking it afterwards
    _RESET_STEPPER_CURRENT      # resetting the stepper current
    M117
```

Then the `CALIBRATE_Z` command needs to be added to the `PRINT_START` macro. For this,
just replace the second Z homing after QGL and nozzle cleaning with the calibration. A
second homing is not needed anymore.

**:exclamation: And remove any Z offset adjustments here (like `SET_GCODE_OFFSET`) :exclamation:**

The print start sequence could look like this:

1. Home all axes
2. Heat up the bed and nozzle (and chamber)
3. Get probe, make QGL, park probe
4. Purge and clean the nozzle
5. Get probe, CALIBRATE_Z, park probe
6. (Adjust Z offset if needed somehow)
7. Print intro line
8. Start printing...

I don't get any reasons, but if you still need to adjust the offset from your Slicers
start GCode, then add this to your `PRINT_START` macro **after** the Z calibration:

```
    # Adjust the G-Code Z offset if needed
    SET_GCODE_OFFSET Z_ADJUST={params.Z_ADJUST|default(0.0)|float} MOVE=1
```

Then, you can use `Z_ADJUST=0.0` in your Slicer. This does **not** reset to a fixed
offset but adjusts it by the given value!

>:pencil2: **NOTE:** Do not home Z again after running this calibration or it needs to be executed again!

Now, I wish you happy printing with an always perfect first layer - doesn't matter what you just
modded on your printer's head or bed or what nozzle and flex plate you like to use for your next
project. It's just perfect :smiley:

### Command PROBE_Z_ACCURACY

There is also a PROBE_Z_ACCURACY command to test the accuracy of the Z endstop:

```
PROBE_Z_ACCURACY [PROBE_SPEED=<mm/s>] [LIFT_SPEED=<mm/s>] [SAMPLES=<count>] [SAMPLE_RETRACT_DIST=<mm>]
```

It calculates the maximum, minimum, average, median and standard deviation of multiple probe samles on
the endstop by taking the configured nozzle position on the endstop. The optional parameters default
to their equivalent setting in the z_calibration config section.

## Disclaimer

:construction::construction_worker: It works flawlessly for me. But, at this moment it is not widely tested. And I don't know
much about the Klipper internals. So, I had to figure it out by myself and found this as a
working way for me. If there are better/easier ways to accomplish it, please don't
hesitate to contact me!
