# Tarnwick Robotics TR-GR40 "Kestrel" Gantry Rover

## Python SDK Reference and Integration Manual

**SDK package:** `tarnwick_rover` version 3.2.1
**Controller firmware:** KCF 5.8.x
**Document number:** TRW-DOC-GR40-SDK-0321, revision F
**Applies to:** TR-GR40 serial numbers GR40-24-0001 and later, TR-GR40-L (long rail) where noted

> This is a fictional product manual written as sample material for RoboDE's control-adapter workflow. Tarnwick
> Robotics, the TR-GR40 and the `tarnwick_rover` SDK do not exist. All specifications, part numbers, addresses and
> test results are invented. Do not use any of it to operate real equipment.

---

## Contents

1. Revision history
2. About this manual
3. About Tarnwick Robotics and the GR product family
4. Safety
5. Product overview
6. Technical specifications
7. Axis definitions, limits and sign conventions
8. Coordinate frames
9. Electrical interfaces and connectors
10. Networking and security
11. Installing the SDK
12. Quick start
13. API reference
14. Motion behaviour and timing
15. Status, feedback and telemetry
16. Error and fault codes
17. Status lights and sounds
18. Calibration and homing
19. Maintenance schedule
20. Troubleshooting
21. Frequently asked questions
22. Firmware and SDK change log
23. Appendices

---

## 1. Revision history

| Revision | Date | Author | Summary |
| --- | --- | --- | --- |
| A | 2024-03-02 | M. Okonkwo | First release for SDK 1.0 and firmware KCF 4.2 |
| B | 2024-07-19 | M. Okonkwo, R. Lindqvist | Added drive wheel velocity commands and odometry |
| C | 2024-11-30 | R. Lindqvist | SDK 2.0: millimetre and degree units everywhere; inch API deprecated |
| D | 2025-04-08 | P. Anand | Heartbeat watchdog made mandatory; new fault codes E3xx |
| E | 2025-09-14 | P. Anand, S. Ferreira | Batch arm command `move_arm`; TR-GR40-L long rail variant |
| F | 2026-02-21 | S. Ferreira | SDK 3.2.1; jaw force limit; corrected lift sign diagram; editorial fixes |

Changes in revision F are marked with a vertical bar in the printed edition. The online edition does not show change bars.

---

## 2. About this manual

This manual is written for integrators who control the TR-GR40 from their own software. It assumes familiarity with Python 3, basic networking and the safety practices of your site. Operators who only use the handheld pendant should read the TR-GR40 Operator Guide (TRW-DOC-GR40-OPS) instead.

Conventions used in this manual:

- `monospace` marks code, method names, file names and values you type.
- **Warning** marks a hazard that can cause injury.
- **Caution** marks a hazard that can damage the equipment or the payload.
- **Note** marks information that helps you avoid mistakes.
- Numbers use a full stop as the decimal separator. Negative values use a hyphen.
- Unless stated otherwise, linear values are in millimetres (mm), angles are in degrees (deg), wheel speeds are in radians per second (rad/s), time is in seconds (s) and mass is in kilograms (kg).

The SDK reports and accepts values in these units only. There is no unit selection setting in SDK 3.x.

---

## 3. About Tarnwick Robotics and the GR product family

Tarnwick Robotics designs mobile handling platforms for laboratories, light assembly and education. The company was founded in 2016 in a converted textile mill and moved to its current site in 2021. Its first product, the TR-B10 bench gantry, is still sold for teaching. The GR ("gantry rover") family combines a differential-drive chassis with an on-board Cartesian gantry and a small arm, so that one machine can move between benches and then position a tool precisely at each one.

| Model | Rail travel (X) | Beam travel (Y) | Lift travel (Z) | Arm | Payload | Status |
| --- | --- | --- | --- | --- | --- | --- |
| TR-GR20 "Wren" | 160 mm | 240 mm | 200 mm | 2-joint | 0.8 kg | Discontinued 2025 |
| TR-GR40 "Kestrel" | 240 mm | 360 mm | 320 mm | 3-joint with jaw | 1.5 kg | Current |
| TR-GR40-L "Kestrel L" | 480 mm | 360 mm | 320 mm | 3-joint with jaw | 1.5 kg | Current, made to order |
| TR-GR60 "Osprey" | 400 mm | 600 mm | 450 mm | 4-joint with tool changer | 4.0 kg | Announced |

The GR40 and GR40-L use the same SDK. On the GR40-L the rail range is wider (see section 7). Everything else in this manual applies to both unless stated.

Tarnwick's support desk is staffed 08:00 to 17:30 on working days. Response targets are 4 working hours for line-down cases and 2 working days for questions. The company also runs a quarterly user meeting and keeps a public forum, which is not monitored for urgent issues.

---

## 4. Safety

**Warning:** The TR-GR40 is a moving machine with exposed axes. It is not a collaborative robot. Fence or mark its working area, and keep people out of the area while it is under software control.

**Warning:** The gantry lift and the arm can trap fingers between the lift carriage and the beam, and between the jaw and the fixed finger. Never reach into the gantry while the drives are enabled.

**Warning:** The battery pack stores about 1.9 kWh. Do not open, crush, puncture or short-circuit it. Charge only with the supplied charger, model TR-CHG-48-10.

**Warning:** The red emergency stop buttons on both sides of the chassis cut power to all motors through a safety relay. Software stop commands, including `halt()`, are not a substitute for the emergency stop circuit.

**Caution:** Do not drive the rover with the lift extended more than 200 mm. The centre of gravity rises and the rover can tip on slopes or during hard braking. Firmware 5.6 and later limit drive speed automatically when the lift is extended beyond 200 mm (see section 14).

**Caution:** Do not lift the rover by the gantry frame. Use the four lifting points on the chassis and a sling rated for at least 100 kg.

**Caution:** Remove the jaw protective sleeve before the first power-up. Commanding the jaw with the sleeve fitted triggers fault E214.

Risk reduction measures built into the product:

- Dual-channel emergency stop, category 0 stop to the motor drives.
- Speed and separation monitoring is **not** provided. Add a site scanner if people share the area.
- Each axis has hardware end-of-travel switches about 3 mm beyond the software limit.
- The jaw force is limited by current to 40 N. The arm joints are torque limited (section 6).
- A heartbeat watchdog stops all motion if the controlling program goes silent (section 13.9).
- The drive wheels have spring-applied brakes that engage when power is lost.

Tarnwick evaluated the GR40 against its internal procedure TP-114 (mobile manipulator hazards). The evaluation report is available to customers on request. It is not a certification.

---

## 5. Product overview

The TR-GR40 consists of:

1. **Chassis:** a welded aluminium frame with two driven wheels, two passive casters, the battery pack, the controller, and the emergency stop buttons.
2. **Gantry frame:** two posts and a cross beam bolted to the chassis.
3. **Rail shuttle (X axis):** carries the beam fore and aft along the chassis rails.
4. **Beam carriage (Y axis):** travels across the beam, left and right.
5. **Lift (Z axis):** a ball-screw lift on the beam carriage that extends downward.
6. **Arm:** three revolute joints below the lift: J1 yaw, J2 pitch and J3 pitch.
7. **Jaw gripper:** one moving jaw against a fixed finger.

The controller (KC-5 board) runs firmware KCF 5.8 and exposes a TCP command port and a UDP telemetry stream on its Ethernet interface. The SDK wraps both. A handheld pendant (TR-PND-2) can be connected to the front service port; when the pendant is in control, SDK motion commands are rejected with fault E402.

The rover is designed for indoor use on flat, smooth floors such as sealed concrete, vinyl or epoxy. It is not suitable for carpet, gravel, outdoor use or wet floors.

---

## 6. Technical specifications

### 6.1 General

| Item | Value |
| --- | --- |
| Overall length × width × height (lift retracted) | 640 × 500 × 1010 mm |
| Chassis length × width × height | 600 × 440 × 160 mm |
| Mass, without payload | 54 kg |
| Rated payload at the jaw | 1.5 kg |
| Maximum payload on the chassis deck | 15 kg |
| Footprint for navigation (rectangle) | 640 × 500 mm |
| Ground clearance | 22 mm |
| Construction | Aluminium 6082-T6 frame, anodised; ABS covers |
| Colour | Signal grey with Tarnwick blue covers |
| Ingress protection | IP20 (indoor, dry) |
| Operating temperature | 5 to 40 °C |
| Storage temperature | -10 to 50 °C |
| Relative humidity | 10 to 85 %, non-condensing |
| Sound pressure at 1 m, driving | 58 dB(A) |
| Sound pressure at 1 m, gantry moving | 54 dB(A) |
| Design life | 20 000 operating hours |

### 6.2 Drive and chassis

| Item | Value |
| --- | --- |
| Drive type | Differential drive, two driven wheels, two passive casters |
| Drive wheel diameter | 160 mm (radius 80 mm) |
| Track width (wheel centre to wheel centre) | 460 mm |
| Caster diameter | 70 mm |
| Wheel motors | 2 × brushless DC, 180 W, 48 V |
| Gearbox ratio | 16:1 planetary |
| Maximum wheel speed | 12 rad/s |
| Maximum linear speed | 0.96 m/s (firmware limits to 0.6 m/s by default) |
| Maximum turn rate in place | 2.4 rad/s (firmware limits to 1.2 rad/s by default) |
| Maximum wheel acceleration | 6 rad/s² |
| Braking distance from 0.6 m/s | 0.12 m (controlled stop), 0.25 m (emergency stop) |
| Maximum slope | 4 degrees with lift retracted, 2 degrees with lift extended |
| Maximum step height | 10 mm at low speed |
| Encoders | 4096 counts per motor revolution, quadrature |
| Odometry drift (typical) | 1.5 % of distance travelled on sealed concrete |

### 6.3 Gantry axes

| Axis | Travel | Max speed | Max acceleration | Repeatability | Drive |
| --- | --- | --- | --- | --- | --- |
| X rail shuttle | 240 mm (-120 to 120) | 200 mm/s | 400 mm/s² | ±0.05 mm | Belt, 3 mm pitch, 24 teeth pulley |
| Y beam carriage | 360 mm (-180 to 180) | 250 mm/s | 400 mm/s² | ±0.05 mm | Belt, 3 mm pitch, 20 teeth pulley |
| Z lift | 320 mm (0 to 320, downward) | 150 mm/s | 300 mm/s² | ±0.02 mm | Ball screw, 10 mm lead |

On the TR-GR40-L, the X rail travel is 480 mm (-240 to 240). All other values are the same.

### 6.4 Arm and jaw

| Joint | Range | Max speed | Max acceleration | Rated torque | Link length |
| --- | --- | --- | --- | --- | --- |
| J1 yaw (shoulder) | -149 to 149 deg | 80 deg/s | 115 deg/s² | 24 N·m | 250 mm to J2 |
| J2 pitch (elbow) | -115 to 115 deg | 92 deg/s | 115 deg/s² | 14 N·m | 220 mm to J3 |
| J3 pitch (wrist) | -104 to 104 deg | 115 deg/s | 140 deg/s² | 6 N·m | 140 mm to tool tip |
| Jaw opening | 0 to 45 mm | 50 mm/s | 200 mm/s² | 40 N grip force limit | Fixed finger + moving jaw |

The J1 axis is vertical. J2 and J3 pitch about axes parallel to the beam carriage's Y direction when J1 is at 0 deg. The tool tip is 140 mm beyond the J3 axis along the wrist, between the jaw and the fixed finger.

### 6.5 Battery and power

| Item | Value |
| --- | --- |
| Chemistry | LiFePO4 |
| Nominal voltage | 48 V |
| Capacity | 40 Ah (1.92 kWh) |
| Typical runtime | 7 h at 30 % duty, 4 h at continuous driving |
| Charge time, 10 % to 90 % | 3.5 h with TR-CHG-48-10 |
| Charging connector | Rear panel, 3-pin, keyed |
| Auxiliary output | 24 V, 3 A on the deck connector |
| Standby consumption | 14 W |
| Battery management | Internal BMS; state of charge reported in telemetry |

### 6.6 Controller

| Item | Value |
| --- | --- |
| Controller board | KC-5, dual-core 1.2 GHz, real-time co-processor |
| Control loop rate | 1 kHz for axes, 200 Hz for wheels |
| Command port | TCP 7400 |
| Telemetry | UDP 7401, 50 Hz default, 10 to 200 Hz configurable |
| Service web page | HTTP 80 (disabled by default from firmware 5.7) |
| Storage | 8 GB, logs kept for 30 days |
| Clock | NTP client; falls back to the real-time clock |

---

## 7. Axis definitions, limits and sign conventions

The SDK names each axis with a short vendor identifier. These names appear in method names, telemetry fields and fault messages.

| SDK axis name | Physical axis | Unit | Lower limit | Upper limit | Positive direction |
| --- | --- | --- | --- | --- | --- |
| `rail_x` | X rail shuttle | mm | -120 | 120 | Toward the front of the rover |
| `beam_y` | Y beam carriage | mm | -180 | 180 | Toward the rover's left side |
| `lift_z` | Z lift extension | mm | 0 | 320 | **Downward** (extending lowers the arm) |
| `j1_yaw` | Arm J1 | deg | -149 | 149 | Counter-clockwise seen from above |
| `j2_pitch` | Arm J2 | deg | -115 | 115 | Raises the forearm when J1 is at 0 |
| `j3_pitch` | Arm J3 | deg | -104 | 104 | Raises the wrist when J2 is at 0 |
| `jaw` | Jaw opening | mm | 0 | 45 | Opening |
| `drive_left` | Left wheel speed | rad/s | -12 | 12 | Forward rolling |
| `drive_right` | Right wheel speed | rad/s | -12 | 12 | Forward rolling |

**Note:** Revision E of this manual showed the lift arrow pointing up. That diagram was wrong. Positive `lift_z` has always meant extension downward.

**Note:** The software limits above are what the controller accepts. Hardware end-of-travel switches sit about 3 mm (or 2 degrees) beyond them. Reaching a hardware switch raises fault E120 and requires a reset.

On the TR-GR40-L, `rail_x` accepts -240 to 240 mm. Calling `get_model()` returns `"TR-GR40-L"` on those machines. Integrators who support both models should read the range from `get_axis_limits()` rather than hard-coding it.

---

## 8. Coordinate frames

The controller uses four frames:

- **`map`:** the site frame, if a map has been loaded with `load_map()`. Not used by the motion commands in this manual.
- **`odom`:** fixed at the rover's position when the controller started or when `reset_odometry()` was last called. X forward, Y left, Z up.
- **`base_link`:** on the floor directly below the midpoint between the drive wheels. X forward, Y left, Z up.
- **`tool`:** at the tool tip between the jaw and fixed finger.

The gantry frame origin is 220 mm above `base_link`. The rail shuttle's zero position puts the beam directly above the drive wheel axle. With all axes at zero, the J1 axis is 840 mm above the floor, and the tool tip points forward along X.

The SDK does not compute inverse kinematics. Commands set individual axes. A forward-kinematics helper, `tool_pose()`, returns the tool position in `base_link` for the current axis values. Customers who need Cartesian motion compute it in their own software.

---

## 9. Electrical interfaces and connectors

### 9.1 Rear panel

| Connector | Type | Purpose |
| --- | --- | --- |
| X1 | 3-pin keyed, 30 A | Charger input |
| X2 | RJ45 | Ethernet, 1 Gbit/s |
| X3 | M12 A-coded, 8-pin | Safety I/O (external stop in, stop status out) |
| X4 | USB-C | Service only; not used by the SDK |
| X5 | 2-pin | Main power switch remote |

### 9.2 Deck

| Connector | Type | Purpose |
| --- | --- | --- |
| X10 | M8, 4-pin | 24 V auxiliary, 3 A |
| X11 | M8, 4-pin | Two digital inputs, two digital outputs (24 V) |
| X12 | M12, 5-pin | CAN for accessories, 500 kbit/s |

### 9.3 Safety I/O pinout (X3)

| Pin | Signal | Notes |
| --- | --- | --- |
| 1 | ESTOP_IN_A+ | Channel A, 24 V, must be closed to run |
| 2 | ESTOP_IN_A- | |
| 3 | ESTOP_IN_B+ | Channel B, 24 V, must be closed to run |
| 4 | ESTOP_IN_B- | |
| 5 | STOP_OUT_A | Volt-free contact, opens when stopped |
| 6 | STOP_OUT_B | Volt-free contact, opens when stopped |
| 7 | 0 V | |
| 8 | Shield | |

A bridging plug (part TR-ACC-X3-BRG) is fitted at the factory. Replace it with your site's safety circuit before use.

### 9.4 Accessory CAN map (X12)

| ID (hex) | Direction | Content |
| --- | --- | --- |
| 0x120 | Rover → accessory | Rover state, 20 Hz |
| 0x121 | Rover → accessory | Battery and fault summary, 2 Hz |
| 0x1A0 | Accessory → rover | Accessory heartbeat |
| 0x1A1 | Accessory → rover | Accessory request (reserved) |

The SDK does not expose the CAN bus. Accessories are configured through the service page.

---

## 10. Networking and security

### 10.1 Defaults

| Setting | Default |
| --- | --- |
| IP address | 192.168.40.2 |
| Subnet mask | 255.255.255.0 |
| Gateway | none |
| DHCP | off |
| Command port | TCP 7400 |
| Telemetry | UDP 7401 to the last connected client |
| Service page | disabled |
| Access token | printed on the label inside the rear cover |

### 10.2 Access token

Every connection must present the rover's access token. Store it in an environment variable or a secrets manager; do not write it into source code. Rotate the token from the service page or with the `tarnwick-admin rotate-token` tool. Rotating the token drops all current connections.

### 10.3 Encryption

From firmware 5.7, the command port accepts TLS 1.3. Pass `tls=True` to `RoverClient`. The rover presents a self-signed certificate unless you install your own from the service page. Telemetry over UDP is not encrypted; it carries no commands.

### 10.4 One controlling client

Only one client may hold motion control at a time. A second client can connect for telemetry only. The first client to call `enable()` takes control. A client loses control when it calls `release()`, disconnects, or misses the heartbeat deadline.

---

## 11. Installing the SDK

Supported: Python 3.9 to 3.12 on Linux x86-64, Linux arm64, Windows 10/11 x64 and macOS 13 or later.

```sh
python -m pip install tarnwick-rover==3.2.1
```

The package has no compiled dependencies. It depends on `numpy` (1.24 or later) for the forward-kinematics helper only.

Verify the installation:

```sh
python -c "import tarnwick_rover; print(tarnwick_rover.__version__)"
```

The command line tool `tarnwick-admin` is installed with the package. Run `tarnwick-admin --help` for its commands, which include `discover`, `rotate-token`, `logs`, `firmware` and `selftest`.

---

## 12. Quick start

```python
import os, time
import tarnwick_rover

client = tarnwick_rover.RoverClient("192.168.40.2", token=os.environ["TARNWICK_TOKEN"])
client.connect()
client.enable()

try:
    client.home_all()
    client.set_beam_y(50)
    client.set_lift_z(120)
    client.set_j1_yaw(30)
    client.set_jaw_opening(40)
    while client.is_moving():
        client.heartbeat()
        time.sleep(0.1)
    print(client.read_state())
finally:
    client.halt()
    client.close()
```

The program connects, takes control, homes, moves four axes, keeps the heartbeat going while waiting, prints the final state, then stops and closes the connection.

---

## 13. API reference

All methods are on `tarnwick_rover.RoverClient` unless stated. Methods that command motion return immediately; motion continues in the controller. Methods raise `tarnwick_rover.RoverError` (or a subclass) on failure.

### 13.1 Construction and connection

`RoverClient(host, port=7400, token=None, tls=False, timeout_s=2.0)` creates a client object and does not open a connection.

`connect()` opens the command connection and starts receiving telemetry. It raises `ConnectionError` if the rover is unreachable and `AuthError` if the token is wrong.

`enable()` takes motion control and energises the drives. It raises `ControlError` (fault E401) if another client holds control, or E402 if the pendant is in control.

`release()` gives up motion control without disconnecting. Drives stay energised but hold position.

`close()` stops all motion, releases control and closes the connection. Always call `close()` when your program ends, including on error paths.

`get_model()` returns the model string, either `"TR-GR40"` or `"TR-GR40-L"`.

`get_firmware_version()` returns the firmware version string, for example `"KCF 5.8.2"`.

`get_axis_limits()` returns a dictionary of the software limits for every axis in the units of section 7.

### 13.2 Gantry axis commands

`set_rail_x(position_mm)` drives the X rail shuttle to an absolute position between -120 and 120 mm.

On the TR-GR40-L, the same method accepts -240 to 240 mm; see section 7.

`set_beam_y(position_mm)` drives the Y beam carriage to an absolute position between -180 and 180 mm.

`set_lift_z(extension_mm)` extends the Z lift downward to an absolute extension between 0 and 320 mm.

A value of 0 fully retracts the lift. Larger values lower the arm toward the floor.

### 13.3 Arm joint commands

`set_j1_yaw(angle_deg)` rotates arm joint J1 to an absolute angle between -149 and 149 deg.

`set_j2_pitch(angle_deg)` rotates arm joint J2 to an absolute angle between -115 and 115 deg.

`set_j3_pitch(angle_deg)` rotates arm joint J3 to an absolute angle between -104 and 104 deg.

The three arm joints can also be commanded together:

`move_arm(targets)` sets several arm joints in one call, where `targets` is a dictionary keyed by `"j1_yaw"`, `"j2_pitch"` and `"j3_pitch"` with absolute angles in degrees inside each joint's range from section 7.

Joints missing from `targets` keep their current setpoint. `move_arm` starts all listed joints at the same time and scales their speeds so they arrive together.

### 13.4 Jaw command

`set_jaw_opening(opening_mm)` opens or closes the jaw to an absolute opening between 0 and 45 mm.

The jaw stops early if the grip force reaches the configured limit. The state then reports `jaw_contact: true`. The force limit is set with `set_jaw_force(newtons)`, which accepts 5 to 40 N and does not move the jaw.

### 13.5 Drive wheel commands

`set_drive_left(speed_rad_s)` sets the left wheel to a signed angular speed between -12 and 12 rad/s.

`set_drive_right(speed_rad_s)` sets the right wheel to a signed angular speed between -12 and 12 rad/s.

Wheel speed commands stay in effect until changed, until `halt()`, or until the heartbeat deadline passes. They are not distance commands. To travel a distance, command a speed and set it back to 0 after the computed time, or use your own odometry loop.

Firmware limits the effective linear speed to 0.6 m/s and the turn rate to 1.2 rad/s by default, even if the wheel commands would exceed them. Raise these limits on the service page only after a site risk assessment.

### 13.6 Motion helpers

`home_all()` homes all gantry axes and arm joints in the order Z, Y, X, J1, J2, J3, jaw. It takes about 25 s and blocks until done.

`is_moving()` returns `True` while any axis or wheel is moving.

`wait_idle(timeout_s=30.0)` blocks until no axis is moving, calling `heartbeat()` internally. It raises `TimeoutError` if motion has not finished in time.

`set_speed_scale(factor)` scales the maximum speed of every gantry axis and arm joint by a factor between 0.1 and 1.0.

The speed scale does not move anything and does not apply to the drive wheels. It resets to 1.0 at power-up.

`tool_pose()` returns the tool tip position `(x_mm, y_mm, z_mm)` and the tool pitch in degrees, in the `base_link` frame, from the current axis values.

### 13.7 Feedback

`read_state()` returns a dictionary with the latest measured position of every axis, every wheel speed, the battery state, the active faults and the stopped flag.

Example result:

```python
{
    "timestamp": 1761900000.125,
    "positions": {"rail_x": 0.0, "beam_y": 50.0, "lift_z": 120.0,
                  "j1_yaw": 30.0, "j2_pitch": 0.0, "j3_pitch": 0.0, "jaw": 40.0},
    "wheel_speeds": {"drive_left": 0.0, "drive_right": 0.0},
    "odometry": {"x_m": 0.0, "y_m": 0.0, "yaw_rad": 0.0},
    "stopped": True,
    "jaw_contact": False,
    "battery": {"soc_percent": 82, "voltage_v": 51.2, "current_a": -1.3},
    "faults": [],
    "control": "sdk"
}
```

Positions are in the units of section 7. `stopped` is `True` only when every axis and wheel has been within its in-position window for at least 100 ms.

`subscribe(callback, rate_hz=50)` calls `callback(state)` from a background thread for every telemetry packet. Keep the callback short; slow callbacks drop packets.

### 13.8 Stopping

`halt()` decelerates every axis and both wheels to a controlled stop within 0.5 s and holds position with the drives energised.

`halt()` is a software stop. It does not replace the emergency stop circuit. After `halt()`, new motion commands are accepted immediately.

`quick_stop()` stops faster (about 0.15 s), with higher stress on the mechanics. Use it for software-detected hazards only.

### 13.9 Heartbeat watchdog

`heartbeat()` resets the controller's watchdog and must be called at least every 0.5 s while the client holds control, or the controller halts all motion and raises fault E305.

The heartbeat is mandatory from firmware 5.5. `wait_idle()` and `home_all()` send heartbeats internally. A background heartbeat thread is available with `start_heartbeat_thread()`, but Tarnwick recommends calling `heartbeat()` from your control loop, so that a hung control loop also stops the robot.

### 13.10 Deprecated methods

These methods remain for compatibility and will be removed in SDK 4.0. Do not use them in new code.

`set_lift(inches)` was the SDK 1.x lift command, which accepted 0 to 12.6 inches with the old upward sign convention, and it is deprecated since SDK 2.0.

`drive(linear_mps, angular_rps)` was the SDK 1.x drive command, deprecated since SDK 2.0 because it hid the per-wheel limits.

`gripper(open)` took a boolean and opened or closed the jaw fully. It is deprecated since SDK 2.0; use `set_jaw_opening()`.

### 13.11 Miscellaneous

`set_beacon(color)` sets the beacon colour to one of `"off"`, `"green"`, `"amber"`, `"blue"` or `"white"`.

`play_tone(name)` plays one of the built-in tones: `"ready"`, `"attention"` or `"done"`.

`reset_odometry()` sets the odometry pose to zero at the current position.

`load_map(path)` loads an occupancy map for the optional navigation module, which this manual does not cover.

`get_log(lines=200)` returns the most recent controller log lines as a list of strings.

### 13.12 Exceptions

| Exception | Raised when |
| --- | --- |
| `RoverError` | Base class of all SDK errors |
| `ConnectionError` | The rover cannot be reached or the connection drops |
| `AuthError` | The access token is wrong or missing |
| `ControlError` | Control is held by another client or the pendant |
| `LimitError` | A command value is outside the axis limits; nothing moves |
| `FaultError` | The controller has an active fault that blocks motion |
| `TimeoutError` | A blocking helper did not finish in time |

`LimitError` is raised before anything is sent to the axis. A rejected command never moves the robot partially.

---

## 14. Motion behaviour and timing

- **Profiles:** gantry axes and arm joints use jerk-limited S-curve profiles. The controller plans each move from the current setpoint, so a new command interrupts the previous one smoothly.
- **Concurrency:** commands to different axes run at the same time. Commands to the same axis replace the previous target.
- **Latency:** typical command-to-motion latency is 4 ms on a direct cable and 15 ms through one switch.
- **In-position windows:** 0.1 mm for gantry axes, 0.2 deg for arm joints, 0.5 mm for the jaw, 0.05 rad/s for wheels.
- **Lift and driving:** when `lift_z` is more than 200 mm, wheel speed is limited to 3 rad/s regardless of the command. When it is more than 280 mm, wheel commands are rejected with fault E231.
- **Arm and chassis clearance:** the controller rejects arm commands that would bring the tool below 40 mm above the floor or into the chassis volume, using the same model as `tool_pose()`. This check raises E232.
- **Speed scale:** `set_speed_scale()` applies to new commands only.
- **Power loss:** axes are held by brakes on Z and J2; X, Y, J1, J3 and the jaw are back-drivable when unpowered. Support the payload before cutting power.

---

## 15. Status, feedback and telemetry

Telemetry packets are sent over UDP at 50 Hz by default. Each packet has a sequence number; the SDK discards out-of-order packets and reports dropped packets with `client.stats()`.

Telemetry fields, in addition to those in `read_state()`:

| Field | Unit | Notes |
| --- | --- | --- |
| `motor_temps_c` | °C | Per motor; warning at 70, fault at 85 |
| `axis_currents_a` | A | Per axis |
| `bus_voltage_v` | V | Motor bus |
| `cpu_load_percent` | % | Controller CPU |
| `loop_overruns` | count | Real-time loop overruns since boot |
| `estop` | bool | Emergency stop circuit open |
| `pendant_connected` | bool | Pendant present |
| `imu` | rad, rad/s | Roll, pitch, yaw rate from the chassis IMU |

The rover also writes an event log, which can be read with `get_log()` or `tarnwick-admin logs`. Logs are rotated daily and kept for 30 days.

---

## 16. Error and fault codes

| Code | Name | Cause | Recovery |
| --- | --- | --- | --- |
| E101 | AXIS_FOLLOWING | Axis could not follow its profile (blocked or overloaded) | Remove obstruction, call `clear_faults()` |
| E110 | ENCODER | Encoder signal lost | Check cable; power cycle |
| E120 | HW_LIMIT | Hardware end switch reached | Jog away with the pendant, then `clear_faults()` |
| E130 | OVERTEMP | Motor temperature above 85 °C | Let it cool; reduce duty |
| E140 | OVERCURRENT | Drive current limit exceeded | Check payload; `clear_faults()` |
| E201 | NOT_HOMED | Motion command before homing | Call `home_all()` |
| E214 | JAW_SLEEVE | Jaw blocked during first opening | Remove the protective sleeve |
| E221 | LIMIT | Command outside software limits | Correct the value (also raised as `LimitError`) |
| E231 | LIFT_DRIVE | Driving with the lift extended more than 280 mm | Retract the lift |
| E232 | CLEARANCE | Tool would hit the floor or chassis | Choose another pose |
| E301 | NET_TIMEOUT | Command connection lost | Reconnect |
| E305 | HEARTBEAT | No heartbeat for 0.5 s | Fix the control loop; `enable()` again |
| E310 | TELEMETRY | Telemetry client unreachable | Check firewall for UDP 7401 |
| E401 | CONTROL_HELD | Another client holds control | Wait or ask it to `release()` |
| E402 | PENDANT | Pendant in control | Set the pendant to "remote" |
| E501 | BATTERY_LOW | State of charge below 10 % | Charge |
| E502 | BATTERY_FAULT | BMS reported a fault | Contact support |
| E601 | ESTOP | Emergency stop circuit open | Release the stop, then `clear_faults()` and `enable()` |
| E701 | CONFIG | Invalid configuration on the controller | Restore defaults from the service page |
| E999 | INTERNAL | Unexpected controller error | Save logs, power cycle, contact support |

`clear_faults()` clears faults whose cause has gone. It does not clear E502, E701 or E999.

---

## 17. Status lights and sounds

| Light (beacon) | Meaning |
| --- | --- |
| Off | Powered off or booting |
| Green, steady | Ready, drives disabled |
| Green, slow flash | Drives enabled, idle |
| Blue, steady | Moving under SDK control |
| Blue, fast flash | Moving under pendant control |
| Amber, steady | Warning (low battery, high temperature) |
| Amber, flashing | Fault active |
| Red, steady | Emergency stop open |
| White, pulsing | Firmware update in progress; do not power off |

| Tone | Meaning |
| --- | --- |
| Two rising beeps | Boot complete |
| One long beep | Fault raised |
| Three short beeps | Heartbeat lost (E305) |
| Continuous chirp | Battery below 5 % |

The beacon colour set with `set_beacon()` overrides the status colour while drives are idle, and the status colour returns while moving or on a fault.

---

## 18. Calibration and homing

Homing is required after every power-up. `home_all()` moves each axis slowly toward its home switch, then to zero. During homing the lift retracts first so the arm clears the deck. Homing order and speeds:

| Order | Axis | Direction | Speed |
| --- | --- | --- | --- |
| 1 | `lift_z` | Retract (up) | 20 mm/s |
| 2 | `beam_y` | Negative | 30 mm/s |
| 3 | `rail_x` | Negative | 30 mm/s |
| 4 | `j1_yaw` | Negative | 10 deg/s |
| 5 | `j2_pitch` | Positive | 10 deg/s |
| 6 | `j3_pitch` | Positive | 10 deg/s |
| 7 | `jaw` | Closing | 5 mm/s |

Factory calibration stores the offset between each home switch and the axis zero. Recalibrate only after replacing a motor, belt, screw or switch, following service procedure TRW-SVC-GR40-07. The SDK has no calibration methods.

Wheel calibration (radius and track width) is stored on the controller and used for odometry. Defaults are 80.0 mm and 460.0 mm. After replacing tyres, run `tarnwick-admin selftest --wheel-calibration` on a 5 m straight line and a 10-turn rotation test.

---

## 19. Maintenance schedule

| Interval | Task | Notes |
| --- | --- | --- |
| Daily | Check emergency stop buttons and beacon | Press each stop, confirm E601, reset |
| Daily | Inspect jaw pads for wear | Replace when grooves are worn flat |
| Weekly | Clean rails and beam with a dry lint-free cloth | No solvents on the belts |
| Weekly | Check tyre surfaces for embedded debris | |
| Monthly | Check belt tension on X and Y | 45 to 55 Hz on the tension meter |
| Monthly | Lubricate the Z ball screw | Tarnwick grease TR-LUB-2, 0.5 g |
| Every 6 months | Replace jaw pads | Part TR-SP-JAW-PAD, pair |
| Every 12 months | Replace X and Y belts | Parts TR-SP-BELT-X, TR-SP-BELT-Y |
| Every 12 months | Battery capacity test | Service tool, about 6 h |
| Every 2 000 hours | Inspect caster bearings | Replace if rough |
| Every 5 000 hours | Replace wheel motor brushes? | Not applicable: motors are brushless. Inspect brakes instead |

Record maintenance in the service log on the controller (`tarnwick-admin logs --service`) so that support can see it.

---

## 20. Troubleshooting

**The rover connects but `enable()` fails with E401.** Another program holds control, often a forgotten script or a notebook kernel. Find it with `tarnwick-admin who`, then close it, or wait 0.5 s after it stops sending heartbeats.

**Motion stops after about half a second and the rover beeps three times.** Your program is not calling `heartbeat()` often enough. Long `time.sleep()` calls are the usual cause.

**`set_lift_z(250)` lowers the lift but driving is very slow.** That is the lift-and-drive interlock (section 14). Retract the lift below 200 mm before driving.

**Odometry drifts more than expected.** Check tyre wear and wheel calibration, and avoid wheel spin by keeping wheel acceleration at 6 rad/s² or below.

**The jaw stops before reaching the commanded opening.** It probably touched an object; check `jaw_contact` in `read_state()`. Raise the force limit with `set_jaw_force()` only if the object can take it.

**Telemetry stops while commands still work.** UDP 7401 is blocked by a firewall, or your computer has two network interfaces and replies come in on the other one.

**The arm command is rejected with E232 although the target looks clear.** The clearance model includes the jaw and a 20 mm margin. Use `tool_pose()` to check the pose the controller computes.

**Values look ten times too large after upgrading from SDK 1.x.** SDK 2.0 changed lift units from inches to millimetres and reversed the lift sign. Remove calls to `set_lift()`.

---

## 21. Frequently asked questions

**Can the TR-GR40 follow a Cartesian path with the tool?** Not by itself. The SDK sets individual axes. Compute the axis values in your own software, then command them, ideally in small steps while watching `read_state()`.

**Is there a ROS 2 driver?** Tarnwick publishes an unsupported community ROS 2 package on its forum. It is not covered by support and is not described in this manual.

**Can I run two rovers from one program?** Yes. Create one `RoverClient` per rover, each with its own token, and send heartbeats to each.

**Does the rover avoid obstacles?** No. The optional navigation module adds a 2D lidar and path planning, and it is sold separately. Without it, the rover drives exactly as commanded.

**What happens if Wi-Fi drops?** The rover has no Wi-Fi. Use a wired Ethernet tether or a site-approved wireless bridge. If the connection drops, the heartbeat watchdog stops motion within 0.5 s.

**Can the jaw report the gripped object's width?** Yes, approximately: `read_state()["positions"]["jaw"]` after `jaw_contact` becomes true, with an accuracy of about ±0.5 mm.

**Why are the arm angles in degrees but the wheels in radians per second?** Wheel speeds follow the motor-control convention used by the drive firmware. Tarnwick considered changing it in SDK 3.0 and decided against breaking existing programs.

**Is a simulator available?** `tarnwick_rover.sim.SimRover` implements the same methods with an idealised model, for unit tests. It does not model dynamics, the interlocks of section 14 or the clearance check.

---

## 22. Firmware and SDK change log

### SDK 3.2.1 (2026-02-10)

- Fixed `wait_idle()` returning early when only the jaw was moving.
- `read_state()` now includes `jaw_contact`.
- Documentation: corrected lift sign diagram.

### SDK 3.2.0 (2025-12-01)

- Added `set_jaw_force()`.
- Added `quick_stop()`.
- `subscribe()` accepts `rate_hz`.

### SDK 3.1.0 (2025-09-14)

- Added `move_arm()`.
- Support for TR-GR40-L.
- `get_axis_limits()` returns per-model limits.

### SDK 3.0.0 (2025-04-08)

- Heartbeat watchdog is mandatory.
- Python 3.8 support removed.
- New exceptions `LimitError` and `FaultError` replace error codes in return values.

### SDK 2.0.0 (2024-11-30)

- All linear values in millimetres and angles in degrees.
- Lift sign reversed: positive extends downward.
- `set_lift()`, `drive()` and `gripper()` deprecated.

### Firmware KCF 5.8.2 (2026-01-20)

- Reduced command latency on busy networks.
- Fixed a rare E110 on the J3 encoder after warm restarts.

### Firmware KCF 5.7.0 (2025-08-02)

- TLS on the command port.
- Service page disabled by default.

### Firmware KCF 5.6.0 (2025-05-11)

- Lift-and-drive interlock (section 14).
- Floor and chassis clearance check for arm commands.

### Firmware KCF 5.5.0 (2025-03-30)

- Heartbeat watchdog enforced in firmware.

---

## 23. Appendices

### Appendix A: Motor and gearbox data

| Axis | Motor | Rated speed | Rated torque | Gear | Encoder |
| --- | --- | --- | --- | --- | --- |
| Drive left / right | BLDC 180 W | 3000 rpm | 0.57 N·m | 16:1 planetary | 4096 cpr |
| X rail | Stepper-servo 1.2 N·m | 1500 rpm | 1.2 N·m | Belt, 24 T | 1000 cpr |
| Y beam | Stepper-servo 0.9 N·m | 1500 rpm | 0.9 N·m | Belt, 20 T | 1000 cpr |
| Z lift | BLDC 100 W with brake | 3000 rpm | 0.32 N·m | Ball screw 10 mm lead | 4096 cpr |
| J1 | Frameless BLDC | 2500 rpm | 0.24 N·m | Harmonic 100:1 | 17-bit absolute |
| J2 | Frameless BLDC with brake | 2500 rpm | 0.14 N·m | Harmonic 100:1 | 17-bit absolute |
| J3 | Frameless BLDC | 3000 rpm | 0.06 N·m | Harmonic 100:1 | 17-bit absolute |
| Jaw | Micro DC | 8000 rpm | 0.01 N·m | Lead screw 1 mm | 512 cpr |

### Appendix B: Environmental test summary

| Test | Condition | Result |
| --- | --- | --- |
| Temperature cycling | 5 to 40 °C, 20 cycles | Pass |
| Humidity | 85 % RH at 30 °C, 48 h | Pass |
| Vibration, transport | Random, 1.0 g rms, 30 min per axis, packaged | Pass |
| Drop, packaged | 0.3 m on each corner | Pass |
| Electrostatic discharge | ±8 kV contact on covers | Pass, no reset |
| Continuous operation | 72 h at 50 % duty | Pass, max motor temperature 61 °C |

These are Tarnwick internal tests. They are not third-party certifications.

### Appendix C: Packing list

- TR-GR40 rover with gantry, arm and jaw
- Battery pack (installed) and charger TR-CHG-48-10 with mains lead
- Safety bridging plug TR-ACC-X3-BRG (fitted)
- Jaw protective sleeve (fitted; remove before use)
- Two spare jaw pads
- Hex key set and belt tension gauge
- Quick start card and access token label (inside the rear cover)
- USB stick with this manual, the Operator Guide and the SDK wheel files

### Appendix D: Spare parts

| Part number | Description |
| --- | --- |
| TR-SP-JAW-PAD | Jaw pads, pair |
| TR-SP-BELT-X | X rail belt |
| TR-SP-BELT-Y | Y beam belt |
| TR-SP-TYRE-160 | Drive tyre, 160 mm |
| TR-SP-CASTER-70 | Caster assembly, 70 mm |
| TR-SP-ESTOP | Emergency stop button with contact block |
| TR-LUB-2 | Ball-screw grease, 10 g |
| TR-CHG-48-10 | Charger, 48 V 10 A |
| TR-PND-2 | Handheld pendant |
| TR-ACC-LIDAR-NAV | Navigation module with lidar |

### Appendix E: Warranty

The TR-GR40 carries a 24-month warranty on parts and labour from the delivery date, and 12 months on the battery pack. Wear parts (jaw pads, belts, tyres, casters) are excluded. The warranty is void if the controller is opened, if non-Tarnwick firmware is installed, or if the safety circuit has been bypassed in operation.

### Appendix F: Glossary

| Term | Meaning |
| --- | --- |
| Axis | Any controlled degree of freedom: a gantry slide, an arm joint, the jaw or a wheel |
| Heartbeat | A periodic message proving the controlling program is alive |
| Home switch | A switch that defines an axis's reference position |
| In-position window | How close an axis must be to its target to count as arrived |
| Odometry | Position estimated from wheel encoders |
| Pendant | The handheld controller used for manual jogging |
| Setpoint | The target value most recently commanded for an axis |
| Software limit | The range the controller accepts for an axis |
| S-curve | A motion profile with limited jerk |
| Track width | The distance between the centres of the two drive wheels |

### Appendix G: Example: drive a short distance and pick from a bench

```python
import math, os, time
import tarnwick_rover

WHEEL_RADIUS_M = 0.080

def drive_straight(client, distance_m, speed_rad_s=4.0):
    duration = abs(distance_m) / (WHEEL_RADIUS_M * speed_rad_s)
    sign = 1 if distance_m >= 0 else -1
    client.set_drive_left(sign * speed_rad_s)
    client.set_drive_right(sign * speed_rad_s)
    end = time.monotonic() + duration
    while time.monotonic() < end:
        client.heartbeat()
        time.sleep(0.05)
    client.set_drive_left(0)
    client.set_drive_right(0)
    client.wait_idle()

client = tarnwick_rover.RoverClient("192.168.40.2", token=os.environ["TARNWICK_TOKEN"])
client.connect()
client.enable()
try:
    client.home_all()
    client.set_lift_z(0)
    client.wait_idle()
    drive_straight(client, 0.75)
    client.set_jaw_opening(45)
    client.move_arm({"j1_yaw": 0, "j2_pitch": -30, "j3_pitch": -60})
    client.set_lift_z(180)
    client.wait_idle()
    client.set_jaw_opening(20)
    client.wait_idle()
    client.set_lift_z(60)
    client.wait_idle()
    print(client.read_state()["jaw_contact"])
finally:
    client.halt()
    client.close()
```

This example ignores the floor and chassis clearance check. In practice, check `tool_pose()` before lowering the lift.

---

*End of document TRW-DOC-GR40-SDK-0321 revision F.*
