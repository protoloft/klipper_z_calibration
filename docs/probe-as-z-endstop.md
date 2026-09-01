# Feasibility: probe as Z endstop, Z pin switch as calibration endstop

Status: implemented. This document is the design record; the sections
below describe the state before the change and what it cost.
Two of its original claims turned out to be wrong and are corrected
in place.

## The request

Keep the dockable magnet probe as the Z homing endstop
(`[stepper_z] endstop_pin: probe:z_virtual_endstop`) and still run
`CALIBRATE_Z` against the physical Z pin switch next to the bed. In that
setup the Z pin switch is no longer a configured endstop of any stepper,
so Klipper does not know about it at all.

## Does the math still hold?

Yes. `CalibrationRun.calibrate_z` computes

    offset = probe_zero - (switch_zero - nozzle_zero + switch_offset)

All three measured terms are trigger positions taken in the same Z
coordinate system during one command. The homing reference that defined
that coordinate system appears in every term with the same sign and
cancels. Which endstop homed Z therefore does not enter the formula, and
no sign or term in it would have to change for this setup.

What does change is everything around the formula: the plugin currently
assumes the calibration endstop is the endstop of the Z rail.

## What blocks it today

### 1. The endstop is not discoverable

`HomingCompat.get_z_endstop` (`klipper_compat.py:308`) looks the
calibration endstop up in `query_endstops` or on the kinematic carriage.
Rails register their endstop there themselves
(`GenericPrinterRail.lookup_endstop`), so with a virtual Z endstop the
only Z entry is the probe's `HomingViaProbeHelper`. The Z pin switch is
not registered anywhere. The lookup would find the probe helper, and the
existing guard would reject it with
`"A virtual endstop for z is not supported"`.

### 2. An endstop without Z steppers stops nothing (safety critical)

**Corrected: the filter exists only in current Klipper, and the failure
differs per firmware. Both outcomes are unacceptable.**

Klipper master's `HomingMove.__init__` filters its endstop list:

    self.endstops = [es for es in endstops if es[0].get_steppers()]

An endstop object created from a pin but never given the Z steppers via
`add_stepper()` is silently dropped from the move. The probing move then
runs to `position_min` without any trigger, i.e. the nozzle is driven
into the bed at probing speed, and `probing_move()` even returns the
start position as the trigger position.

Klipper v0.13.0 and Kalico have no such filter. There the stepper-less
endstop reaches `_calc_endstop_rate`, where `max()` over an empty
`get_steppers()` raises `ValueError` and takes Klippy down. Loud, but
still a failure at the moment of probing.

Because the two shapes cannot be expressed as one upstream source
marker, the guard is a startup contract rather than a contract check:
`RuntimeContractValidator` refuses to start when the calibration endstop
reports no steppers. That check is not limited to a plugin-owned
endstop; a rail endstop without steppers is just as unusable.

### 3. Homing settings never latch

**Corrected. This was overstated and needed no new rail resolution.**

`get_z_rail_settings` / `_is_z_rail` identify the Z rail by object
identity between an endstop and the endstops the rail registered. The
original claim was that a plugin-owned endstop matches no rail, so
`handle_home_rails_end` would never store anything and
`_require_z_homed` would fail permanently with "must home axes first".

That only follows if the rail is matched against the *calibration*
endstop. `HomingViaProbeHelper.setup_pin()` returns `self`
(`klippy/extras/probe.py`), so with `probe:z_virtual_endstop` the Z rail
registers the probe's helper object itself, and both existing lookup
paths find exactly that object. Matching the rail against the *homing*
endstop therefore keeps working unchanged.

The fix was to separate the two roles `z_endstop` played - probing
target and rail identity anchor - not to resolve the rail differently.
The ambiguous axis-based fallback in `_is_z_rail` stays a last resort
and is never reached in this mode.

### 4. `position_z_endstop` means something else

With a virtual endstop Klipper sets
`rail.position_endstop = mcu_endstop.get_position_endstop()`
(`klippy/stepper.py:341`), which for the probe is its `z_offset`. The
suggestion printed by `calibrate_z` (`z_calibration.py:593`),
"new z axis position_endstop=...", would therefore be mislabeled. The
equivalent knob in this configuration is the probe `z_offset`.

## Klipper has no generic "switch" section

There is no config section that just declares a switch and hands out an
endstop object. Everything that can stop a move has to be an MCU endstop
created through `pins.setup_pin('endstop', ...)`, and in upstream Klipper
only three modules call it:

- `klippy/stepper.py` - rails (`stepper_*`, `carriage`, `manual_stepper`),
  which bind the endstop to a stepper and to homing parameters
- `klippy/extras/probe.py` and `klippy/extras/bltouch.py` - the probe
  object, of which there is exactly one, with offsets and probe sessions
- `klippy/extras/tmc.py` - sensorless homing virtual endstops

The switch-shaped sections are not usable here. `[gcode_button]` and
`[filament_switch_sensor]` both go through the `buttons` module, which
polls button state over the MCU's button reporting path. They can run
G-Code on a state change, but they cannot halt a move, and they are not
acceptable as a `probing_move()` target. They would also occupy the pin.

So the pin-level API is the generic mechanism, but it is reachable only
from Python, not from config. A module that wants a plain trigger input
has to set it up itself.

### Reference implementation: `tools_calibrate`

`klippy/extras/tools_calibrate.py` in Kalico (originally from
klipper-toolchanger) already does exactly this, and it is the reference
to compare an implementation against:

- `ProbeEndstopWrapper.__init__` (`tools_calibrate.py:438`) reads a
  `pin:` option, calls `ppins.allow_multi_use_pin()` with the bare pin
  name, then `ppins.lookup_pin(pin, can_invert=True, can_pullup=True)`
  and `mcu.setup_pin("endstop", pin_params)`
- it registers `klippy:mcu_identify` and, in `_handle_mcu_identify`
  (`tools_calibrate.py:469`), attaches every kinematic stepper with
  `is_active_axis(axis)` to that endstop
- it exposes the MCU endstop surface by forwarding, which is the same
  thing `EndstopWrapper` in `klipper_compat.py:270` already does
- it builds *three* such endstops (X, Y and Z) from the *same* pin
  (`tools_calibrate.py:46-48`), which is why the multi-use call is
  there

That last point is the important one: several independent endstop
objects on one physical pin are an established, working pattern, not a
workaround.

## What changed

- **New optional `endstop_pin:` in `[z_calibration]`.** Additive public
  config surface; the section keeps working unchanged without it. The
  pin is set up in `klipper_compat.py` via
  `ppins.setup_pin('endstop', pin)` and registered with
  `query_endstops.register_endstop()` so `QUERY_ENDSTOPS` keeps showing
  it.
- **Attach the Z steppers.** On `klippy:mcu_identify`, walk the
  kinematics and `add_stepper()` every stepper with
  `is_active_axis('z')`. This mirrors what Klipper does internally
  through `probe.LookupZSteppers` without importing probe internals.
- **Reject a stepper-less calibration endstop at startup** in
  `RuntimeContractValidator`, so failure mode 2 can never reach a move.
- **Match the Z rail against the homing endstop, not the calibration
  endstop.** `find_z_homing_endstop()` returns the raw endstop that homes
  Z, whatever its type; `get_z_endstop()` keeps the virtual guard and the
  wrapper on top of it. No alternative rail resolution and no additional
  required options; see the correction under failure mode 3.
- **`_require_z_homed` is unchanged.** `z_homing` still latches, because
  the rail of the virtual endstop is still found.
- **Reword the `position_endstop` suggestion** in this mode (see 4). The
  arithmetic is unchanged, because `rail.position_endstop` *is* the probe
  `z_offset` here; only the name of the knob differs.
- **Keep the virtual endstop guard** for the case where no
  `endstop_pin` is configured, otherwise the current misconfiguration
  error is lost.
- **Tests and contracts.** Extend `tests/fakes.py` with pin setup,
  `add_stepper` and kinematic steppers; add feature-detection tests for
  both modes; extend `scripts/check_klipper_contract.py` with the new
  upstream contracts (`pins.setup_pin`, `stepper.is_active_axis`,
  `query_endstops.register_endstop`). Wiki documentation for the new
  option and the changed macro flow.

## Multi-head setups

The request originates from a toolchanger, where the Z pin already
exists to measure the Z difference between the tool heads - the job
`tools_calibrate` does. The same pin can serve both.

**Sharing the pin works.** `PrinterPins.lookup_pin`
(`klippy/pins.py:96`) rejects a pin that is already active *unless* it
is in `allow_multi_use_pins`, and `allow_multi_use_pin`
(`klippy/pins.py:132`) can be called by either consumer, so section
order does not matter. `setup_pin()` then creates a fresh MCU endstop
object with its own trsync and its own stepper list. Both Klipper and
Kalico have both functions.

**One gotcha:** when the pin is already active, `lookup_pin` returns the
*first* consumer's `pin_params`. A `^` or `!` prefix on the second
consumer's pin is silently ignored, and polarity comes from whoever
registered first. The plugin should therefore either document that or
detect the case and warn.

**Do not reuse the `tools_calibrate` endstop object.** Looking
`tools_calibrate` up and reaching into `probe_multi_axis.mcu_probe[2]`
would couple this plugin to another extra's internals, and that extra
is Kalico-only (on Klipper it is a third-party toolchanger plugin). An
own endstop on a shared pin has no such dependency.

### Open questions specific to multi-head

- **Per-tool result.** Klipper's G-Code offset is global, but the
  calculated offset belongs to the *active* tool. `offset_gcode`
  (`z_calibration.py:76`) already exists for exactly this: it replaces
  `SET_GCODE_OFFSET` with user G-Code, so the result can be routed into
  the toolchanger's per-tool offset. This needs a documented example,
  not new code.
- **Per-tool XY.** `_move` goes through `toolhead.manual_move`, which
  moves in toolhead coordinates and does *not* apply G-Code offsets
  (`klippy/toolhead.py:410`). The XY that places a nozzle over the pin
  therefore differs per tool. The existing `NOZZLE_POSITION` and
  `SWITCH_POSITION` command parameters cover this, so a per-tool macro
  can pass them; the single `nozzle_xy_position` config value cannot.
- **Which steppers get attached.** `is_active_axis('z')` covers a
  shared Z gantry. A tool with its own Z stepper outside the kinematics
  would not be covered, and that case has to be rejected rather than
  silently probed.
- **Which probe is used for the bed.** `CALIBRATE_Z` still needs a
  `[probe]` for the bed measurement. Toolchanger setups with per-tool
  probes may not expose a plain `probe` object, and it is unverified
  what `lookup_object('probe')` returns there. This has to be clarified
  before promising the combination works.

## Risks and open questions

- **Pin conflicts.** By default Klipper rejects a pin that is already
  used elsewhere. `ppins.allow_multi_use_pin()` lifts that, which is
  what `tools_calibrate` does, but sharing the pin with a `buttons`
  consumer is a separate question and should not be enabled blindly.
- **The user-facing sequence changes.** `G28 Z` now needs the probe
  attached, while `CALIBRATE_Z` probes the nozzle first, without the
  probe. Undocking has to happen in `start_gcode`, docking stays in
  `switch_gcode`. The current Wiki example macros do not fit this
  variant.
- **Kalico** uses the same pin and kinematics paths and should work
  unchanged, but that has not been verified against a live Kalico host.
- **Scope.** This is additive but permanently widens the supported setup
  matrix. `AGENTS.md` lists virtual Z endstops *for the calibration
  endstop* as out of scope; this proposal keeps that rule (the
  calibration endstop stays physical) and only changes where the
  calibration endstop comes from.

## Verification notes

Klipper behavior cited above was read from the pinned upstream checkout
in `.compat_repos/klipper-master` and `.compat_repos/kalico-main`
(`klippy/extras/homing.py`, `klippy/extras/probe.py`, `klippy/pins.py`,
`klippy/stepper.py`, `klippy/toolhead.py`,
`klippy/extras/tools_calibrate.py`). Nothing here was executed on
hardware, and no toolchanger configuration was tested.
