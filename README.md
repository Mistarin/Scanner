# Passive RF, BLE, Wi-Fi & GPS Terminal Scanner

A modular terminal scanner and sensor-fusion engine for Linux (CachyOS / Arch / Ubuntu) that combines passive radio observations across Bluetooth BLE, Wi-Fi, RTL-SDR spectrum sweeps, and GPS telemetry.

Rather than relying on a naive device counter, the system applies a **multi-factor statistical classifier** that evaluates:
- $d\text{RSSI}/dt$ signal gradients (approaching vs receding)
- **Bidirectional Spatial Bearing** ($\Delta \text{RSSI} = \text{RSSI}_{\text{front}} - \text{RSSI}_{\text{rear}}$ to indicate `▲ AHEAD`, `▼ BEHIND`, `◄► ALONGSIDE`)
- Co-traveling trajectory variance ($\sigma < 2.5\text{ dB}$ pacing at vehicle speed)
- European ETSI / CEPT / ČTÚ spectrum bands (380–385 MHz uplink, 390–395 MHz downlink TETRA/PEGAS, 433 MHz ISM, 446 MHz PMR, 868 MHz SRD)
- European in-vehicle telematics routers & gateway patterns (Teltonika RUTX, Advantech Conel, Sepura, Škoda Auto)
- High BLE device density clusters vs stationary commuter traffic dampening

### 🔊 Proximity Audio Beeper
- Emits acoustic Geiger-style pulses when target detection probability is elevated ($\ge 35\%$).
- **The closer the target (higher RSSI), the faster the beeping**:
  - Distance $\approx -80\text{ dBm} \to$ Slow pulse (every $\sim 1.6\text{s}$)
  - Distance $\approx -65\text{ dBm} \to$ Medium pulse (every $\sim 0.7\text{s}$)
  - Distance $\approx -50\text{ dBm} \to$ Rapid pulse (every $\sim 0.3\text{s}$)
  - Distance $\ge -40\text{ dBm} \to$ Continuous Geiger warning (every $0.08\text{s}$)
- Non-blocking background worker thread with automatic hardware backend selection (`paplay`, `pw-play`, `aplay`, or terminal bell fallback).
- Mute anytime with `--mute` or `--no-audio`.

---

## Operational Modes Explained

| Mode | Command | Description | Best Used For |
| :--- | :--- | :--- | :--- |
| **Live Sensor Mode** | `python3 main.py` | Probes all local physical USB/PCIe radios (BLE, Wi-Fi, RTL-SDR, GPS), binds active ones, and renders live radar dashboard. | Real-world in-car scanning on laptop or mini-PC. |
| **Simulation Mode** | `python3 main.py --mock` | Executes deterministic 32s repeating scenario loops (Nothing $\to$ Approaching from behind $\to$ Alongside $\to$ Receding). | Testing audio beeper, radar widgets, and math without hardware. |
| **One-Shot Snapshot** | `python3 main.py --oneshot` | Executes a single non-blocking probe pass, outputs a formatted ASCII dashboard snapshot, and terminates cleanly. | Headless cron jobs, diagnostic status checks, or quick CLI inspection. |
| **Telemetry Logger** | `python3 main.py --log out.jsonl` | Streams every classified event, feature score, GPS coordinate, and raw observation to a structured `.jsonl` file. | Collecting empirical drive telemetry for training machine learning models. |

---

## Hardware Shopping & Upgrade Guide

You can start testing with your existing laptop's built-in Bluetooth and GPS. When upgrading to dedicated external hardware, here is the recommended equipment list:

### 1. Core Radio Hardware (SDR & Wireless)
| Part | Search Term (AliExpress / Local) | Approx. Price | Purpose & Benefit |
| :--- | :--- | :--- | :--- |
| **RTL-SDR Receiver** | `RTL-SDR Blog V4 official SMA` | ~700–900 Kč (€30–38) | Sweeps European TETRA (380–395 MHz), PMR446, and ISM telemetry. High TCXO stability. |
| **Dual Bluetooth USB Adapters** | `CSR8510 USB Bluetooth 5.0 adapter` (Buy 2) | ~150–250 Kč (€6–10) | Placed Front and Rear to enable bidirectional bearing ($\Delta\text{RSSI}$). |
| **Monitor-Mode Wi-Fi Dongle** | `MT7612U USB WiFi adapter` or `RTL8812AU` | ~350–550 Kč (€14–22) | Real-time passive 802.11 beacon/probe frame sniffing with Radiotap SNR. |
| **USB GPS Receiver** | `VK-172 USB GPS GLONASS` or `u-blox 7 USB GPS` | ~200–300 Kč (€8–12) | Ground velocity, heading, and spatial coordinate stamping. |

### 2. Antennas & RF Accessories
| Part | Search Term | Approx. Price | Purpose & Benefit |
| :--- | :--- | :--- | :--- |
| **Magnetic Roof Antenna** | `VHF UHF magnetic mount antenna SMA 50 ohm` | ~250–400 Kč (€10–16) | Roof-mounted wideband antenna outside the vehicle Faraday cage. |
| **Dedicated UHF Antenna** | `400MHz UHF magnetic antenna SMA 50 ohm` | ~200–350 Kč (€8–14) | Higher gain tuned specifically for 380–430 MHz emergency and telemetry bands. |
| **Coaxial Extension Cables** | `RG316 SMA male to SMA female 50 ohm 2m` | ~100–180 Kč (€4–7) | Thin 50Ω cable easily routed through car door seals. |

### 3. In-Car Power & USB Infrastructure
| Part | Search Term | Approx. Price | Purpose & Benefit |
| :--- | :--- | :--- | :--- |
| **12V Automotive Buck Converter**| `12V to 5V 5A USB-C buck converter step down` | ~150–250 Kč (€6–10) | Clean 5V/5A power from 12V cigarette lighter/fusebox without voltage spikes. |
| **USB 3.0 Powered Hub** | `USB 3.0 powered hub 4-port 12V/5V` | ~300–500 Kč (€12–20) | Powers multiple SDR dongles and Wi-Fi adapters without laptop USB port brownout. |

---

## Hardware Lifecycle & Dynamic Diagnostics

Every sensor module independently probes its hardware and driver environment:
- **`● ACTIVE`**: Hardware and CLI tools are operational and streaming observations.
- **`▲ STANDBY`**: Hardware detected but blocked or daemon inactive (e.g. `rfkill`, `bluetoothctl power on`).
- **`○ INACTIVE`**: Hardware missing. The dashboard displays a clear diagnostic reason and the exact activation hint (e.g. `Connect RTL-SDR Blog V3/V4 dongle for RF spectrum analysis`).

---

## Usage

You can run the scanner using `python3 main.py` or `python3 -m scanner.main`.

### 1. Live Hardware Mode
Runs the live interactive TUI with attached radios (auto-detects Bluetooth, Wi-Fi, RTL-SDR, GPS):
```bash
python3 main.py
# or
python3 -m scanner.main
```

### 2. Deterministic Simulation Mode
Simulate realistic driving scenarios without requiring any external hardware attached:
```bash
# Patrol vehicle approaching from behind and matching speed with active RF carrier
python3 main.py --mock --scenario patrol_approach

# Standard highway cruising (transient passing cars)
python3 main.py --mock --scenario normal_highway

# Dense city traffic gridlock (verifies traffic jam dampener)
python3 main.py --mock --scenario city_traffic_jam

# Passing a stationary radar / telemetry emitter
python3 main.py --mock --scenario stationary_radar
```

### 3. Diagnostic Snapshot (One-Shot Mode)
Executes a single hardware & spectrum probe snapshot, prints the dashboard output, and exits immediately:
```bash
python3 main.py --oneshot
# or with mock:
python3 main.py --mock --oneshot
```

### 4. Telemetry Logging for Machine Learning Calibration
Record continuous drive sessions to a geo-tagged JSONL log file:
```bash
python3 main.py --log drive_session_01.jsonl
```

---

## Running Unit Tests
Run the full test suite (covering spatial gradients, bidirectional bearing, numerical precision, classifier rules, and hardware fallbacks):
```bash
python3 -m unittest discover tests -v
```
