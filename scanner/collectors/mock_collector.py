"""Deterministic Simulation & Replay Collector for testing and calibration."""

import math
import random
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional
from scanner.collectors.base import BaseCollector
from scanner.models import (
    AntennaPosition,
    GeoFix,
    ModuleHealth,
    ModuleStatus,
    RawObservation,
    SensorType,
    SpectrumBin,
)


class MockCollector(BaseCollector):
    SCENARIOS = {
        "patrol_approach": "Patrol vehicle approaching from behind, matching speed, with active RF carrier",
        "normal_highway": "Standard highway driving (sparse transient devices, high speed, quiet RF)",
        "city_traffic_jam": "Dense stop-and-go commuter traffic (many phones/watches, low speed, no RF spikes)",
        "stationary_radar": "Passing a stationary telemetry/radar emitter at 75 km/h",
    }

    def __init__(self, scenario: str = "patrol_approach"):
        super().__init__(SensorType.MOCK, f"Simulator ({scenario})")
        self.scenario = scenario
        self.start_time = time.time()
        self._buffer: List[RawObservation] = []
        self._bins: Dict[float, SpectrumBin] = {}
        self._lock = threading.Lock()
        self._worker_thread: Optional[threading.Thread] = None
        self.current_fix = GeoFix(latitude=49.1951, longitude=16.6068, speed_kmh=68.0, heading_deg=142.0, has_fix=True)

    def probe_hardware(self) -> ModuleHealth:
        self.health = ModuleHealth(
            sensor=self.sensor_type,
            status=ModuleStatus.ACTIVE,
            display_name=self.display_name,
            diagnostic_reason=f"Synthetic telemetry engine generating scenario '{self.scenario}'.",
            hardware_detected=True,
            required_device="Virtual Simulator Engine",
            activation_hint="Active (Use --mock flag or real hardware modules)."
        )
        return self.health

    def start(self) -> bool:
        self.probe_hardware()
        self.is_running = True
        self.start_time = time.time()
        self._worker_thread = threading.Thread(target=self._sim_loop, daemon=True)
        self._worker_thread.start()
        return True

    def _sim_loop(self):
        while self.is_running:
            t = time.time() - self.start_time
            obs_list = []

            if self.scenario == "patrol_approach":
                # Continuous Cyclic Timeline (32-second repeating cycle):
                # 0-8s:   Nothing / Ambient Baseline (Silent, Low Probability)
                # 8-18s:  Detection Approaching (-82 dBm -> -42 dBm, Beeper accelerating)
                # 18-24s: Peak Proximity (-40 dBm, Maximum Geiger Beeping)
                # 24-32s: Receding back to Nothing (-42 dBm -> -90 dBm, Beeper slowing & silencing)
                cycle_period = 32.0
                phase_time = t % cycle_period

                self.current_fix.speed_kmh = 72.0 + 2.0 * math.sin(t * 0.2)

                if phase_time < 8.0:
                    # Phase 1: NOTHING (Ambient Baseline)
                    # No target devices, RF spectrum baseline only
                    obs_list.append(RawObservation(
                        sensor=SensorType.BLUETOOTH,
                        identifier="A0:11:22:33:44:55",
                        rssi_dbm=-86.0 + random.uniform(-2, 2),
                        name_or_ssid="Generic_Peripheral",
                        channel_or_freq="2.4GHz BLE",
                        vendor="Randomized Address",
                        is_randomized_mac=True
                    ))
                    # Ensure carrier burst is inactive
                    if 391.250 in self._bins:
                        del self._bins[391.250]

                elif phase_time < 18.0:
                    # Phase 2: DETECTION APPROACHING FROM BEHIND (-82 dBm -> -42 dBm)
                    progress = (phase_time - 8.0) / 10.0  # 0.0 to 1.0
                    target_rssi = -82.0 + (progress * 40.0) + random.uniform(-1.0, 1.0)
                    rear_rssi = target_rssi
                    front_rssi = target_rssi - 6.5  # Rear antenna is significantly stronger

                    obs_list.append(RawObservation(
                        sensor=SensorType.BLUETOOTH,
                        identifier="74:A3:4A:91:BB:01",
                        rssi_dbm=rear_rssi,
                        antenna_pos=AntennaPosition.REAR,
                        name_or_ssid="Teltonika_RUTX11_GW",
                        channel_or_freq="2.4GHz BLE",
                        vendor="Teltonika Telematics"
                    ))
                    obs_list.append(RawObservation(
                        sensor=SensorType.BLUETOOTH,
                        identifier="74:A3:4A:91:BB:01",
                        rssi_dbm=front_rssi,
                        antenna_pos=AntennaPosition.FRONT,
                        name_or_ssid="Teltonika_RUTX11_GW",
                        channel_or_freq="2.4GHz BLE",
                        vendor="Teltonika Telematics"
                    ))
                    obs_list.append(RawObservation(
                        sensor=SensorType.BLUETOOTH,
                        identifier="74:A3:4A:91:BB:02",
                        rssi_dbm=rear_rssi - 2.0,
                        antenna_pos=AntennaPosition.REAR,
                        name_or_ssid="Sepura_SC20_TETRA",
                        channel_or_freq="2.4GHz BLE",
                        vendor="Sepura PLC"
                    ))
                    obs_list.append(RawObservation(
                        sensor=SensorType.WIFI,
                        identifier="DC:53:7C:12:88:FF",
                        rssi_dbm=rear_rssi + 3.0,
                        antenna_pos=AntennaPosition.REAR,
                        name_or_ssid="Advantech_SmartFlex_AP",
                        channel_or_freq="5180 MHz (Ch 36)",
                        vendor="Mobile Hotspot",
                        is_mobile_hotspot=True
                    ))

                    # Surrounding BLE peripherals
                    for i in range(8):
                        obs_list.append(RawObservation(
                            sensor=SensorType.BLUETOOTH,
                            identifier=f"E4:5F:01:88:22:{i:02X}",
                            rssi_dbm=target_rssi - 4.0 + random.uniform(-1.5, 1.5),
                            antenna_pos=AntennaPosition.REAR,
                            name_or_ssid=f"BLE_Peripheral_{i}",
                            channel_or_freq="2.4GHz BLE",
                            vendor="Randomized Address",
                            is_randomized_mac=True
                        ))

                    # RF carrier rising in European TETRA/PEGAS Downlink band
                    carrier_snr = 4.0 + (progress * 14.0) + random.uniform(-1.0, 1.0)
                    carrier_pwr = -85.0 + carrier_snr
                    is_burst = carrier_snr > 12.0
                    bin_burst = SpectrumBin(
                        center_freq_mhz=391.250,
                        bandwidth_khz=25.0,
                        power_dbm=round(carrier_pwr, 1),
                        noise_floor_dbm=-88.0,
                        snr_db=round(carrier_snr, 1),
                        is_carrier_burst=is_burst,
                        band_label="TETRA/PEGAS Downlink (EU)"
                    )
                    with self._lock:
                        self._bins[391.250] = bin_burst

                    if is_burst:
                        obs_list.append(RawObservation(
                            sensor=SensorType.SDR_RF,
                            identifier="391.250MHz",
                            rssi_dbm=carrier_pwr,
                            antenna_pos=AntennaPosition.REAR,
                            name_or_ssid=f"TETRA Downlink Burst (+{carrier_snr:.1f}dB SNR)",
                            channel_or_freq="391.250 MHz",
                            vendor="PEGAS Base Station Carrier"
                        ))

                elif phase_time < 24.0:
                    # Phase 3: PEAK PROXIMITY & PACING ALONGSIDE (-40 dBm, Maximum Geiger Alert)
                    target_rssi = -42.0 + random.uniform(-1.2, 1.2)

                    obs_list.append(RawObservation(
                        sensor=SensorType.BLUETOOTH,
                        identifier="74:A3:4A:91:BB:01",
                        rssi_dbm=target_rssi,
                        antenna_pos=AntennaPosition.FRONT,
                        name_or_ssid="Teltonika_RUTX11_GW",
                        channel_or_freq="2.4GHz BLE",
                        vendor="Teltonika Telematics"
                    ))
                    obs_list.append(RawObservation(
                        sensor=SensorType.BLUETOOTH,
                        identifier="74:A3:4A:91:BB:01",
                        rssi_dbm=target_rssi - 0.5,
                        antenna_pos=AntennaPosition.REAR,
                        name_or_ssid="Teltonika_RUTX11_GW",
                        channel_or_freq="2.4GHz BLE",
                        vendor="Teltonika Telematics"
                    ))
                    obs_list.append(RawObservation(
                        sensor=SensorType.BLUETOOTH,
                        identifier="74:A3:4A:91:BB:02",
                        rssi_dbm=target_rssi - 1.5,
                        antenna_pos=AntennaPosition.FRONT,
                        name_or_ssid="Sepura_SC20_TETRA",
                        channel_or_freq="2.4GHz BLE",
                        vendor="Sepura PLC"
                    ))
                    obs_list.append(RawObservation(
                        sensor=SensorType.WIFI,
                        identifier="DC:53:7C:12:88:FF",
                        rssi_dbm=target_rssi + 2.0,
                        antenna_pos=AntennaPosition.FRONT,
                        name_or_ssid="Advantech_SmartFlex_AP",
                        channel_or_freq="5180 MHz (Ch 36)",
                        vendor="Mobile Hotspot",
                        is_mobile_hotspot=True
                    ))

                    for i in range(8):
                        obs_list.append(RawObservation(
                            sensor=SensorType.BLUETOOTH,
                            identifier=f"E4:5F:01:88:22:{i:02X}",
                            rssi_dbm=target_rssi - 4.0 + random.uniform(-1.5, 1.5),
                            name_or_ssid=f"BLE_Peripheral_{i}",
                            channel_or_freq="2.4GHz BLE",
                            vendor="Randomized Address",
                            is_randomized_mac=True
                        ))

                    carrier_snr = 18.0 + random.uniform(-1.0, 1.0)
                    carrier_pwr = -60.0
                    bin_burst = SpectrumBin(
                        center_freq_mhz=391.250,
                        bandwidth_khz=25.0,
                        power_dbm=carrier_pwr,
                        noise_floor_dbm=-88.0,
                        snr_db=carrier_snr,
                        is_carrier_burst=True,
                        band_label="TETRA/PEGAS Downlink (EU)"
                    )
                    with self._lock:
                        self._bins[391.250] = bin_burst

                    obs_list.append(RawObservation(
                        sensor=SensorType.SDR_RF,
                        identifier="391.250MHz",
                        rssi_dbm=carrier_pwr,
                        name_or_ssid=f"TETRA Downlink Burst (+{carrier_snr:.1f}dB SNR)",
                        channel_or_freq="391.250 MHz",
                        vendor="PEGAS Base Station Carrier"
                    ))

                else:
                    # Phase 4: RECEDING AHEAD (-42 dBm -> -88 dBm, Front is stronger as it pulls ahead)
                    progress = (phase_time - 24.0) / 8.0  # 0.0 to 1.0
                    target_rssi = -42.0 - (progress * 46.0) + random.uniform(-1.5, 1.5)

                    obs_list.append(RawObservation(
                        sensor=SensorType.BLUETOOTH,
                        identifier="74:A3:4A:91:BB:01",
                        rssi_dbm=target_rssi,
                        antenna_pos=AntennaPosition.FRONT,
                        name_or_ssid="Teltonika_RUTX11_GW",
                        channel_or_freq="2.4GHz BLE",
                        vendor="Teltonika Telematics"
                    ))
                    obs_list.append(RawObservation(
                        sensor=SensorType.BLUETOOTH,
                        identifier="74:A3:4A:91:BB:01",
                        rssi_dbm=target_rssi - 8.0,
                        antenna_pos=AntennaPosition.REAR,
                        name_or_ssid="Teltonika_RUTX11_GW",
                        channel_or_freq="2.4GHz BLE",
                        vendor="Teltonika Telematics"
                    ))
                    obs_list.append(RawObservation(
                        sensor=SensorType.BLUETOOTH,
                        identifier="74:A3:4A:91:BB:02",
                        rssi_dbm=target_rssi - 2.0,
                        antenna_pos=AntennaPosition.FRONT,
                        name_or_ssid="Sepura_SC20_TETRA",
                        channel_or_freq="2.4GHz BLE",
                        vendor="Sepura PLC"
                    ))

                    # Fade RF carrier
                    if phase_time > 27.0 and 391.250 in self._bins:
                        del self._bins[391.250]

            elif self.scenario == "normal_highway":
                self.current_fix.speed_kmh = 115.0 + random.uniform(-2.0, 2.0)
                # Transient passing car
                passed_rssi = -50.0 - abs(t % 8 - 4) * 8.0
                obs_list.append(RawObservation(
                    sensor=SensorType.BLUETOOTH,
                    identifier="A0:B1:C2:33:44:55",
                    rssi_dbm=passed_rssi,
                    name_or_ssid="Audi MMI_8410",
                    channel_or_freq="2.4GHz BLE",
                    vendor="Automotive In-Car"
                ))
                obs_list.append(RawObservation(
                    sensor=SensorType.WIFI,
                    identifier="00:11:22:33:44:55",
                    rssi_dbm=-82.0 + random.uniform(-3, 3),
                    name_or_ssid="Highway_Toll_Gate_AP",
                    channel_or_freq="2437 MHz (Ch 6)",
                    vendor="Infrastructure"
                ))

            elif self.scenario == "city_traffic_jam":
                self.current_fix.speed_kmh = 8.0 + random.uniform(-3.0, 3.0)
                # Many stationary commuter phones/watches
                for i in range(16):
                    obs_list.append(RawObservation(
                        sensor=SensorType.BLUETOOTH,
                        identifier=f"50:14:79:AA:11:{i:02X}",
                        rssi_dbm=-68.0 + random.uniform(-6, 6),
                        name_or_ssid=f"Commuter_Device_{i}",
                        channel_or_freq="2.4GHz BLE",
                        vendor="Apple / Samsung / Garmin",
                        is_randomized_mac=True
                    ))

            # Populate generic spectrum background bins
            for f in [380.0, 385.0, 390.0, 395.0, 400.0, 433.92, 868.0]:
                if f not in self._bins or not self._bins[f].is_carrier_burst:
                    noise = -90.0 + random.uniform(-2.0, 2.0)
                    self._bins[f] = SpectrumBin(
                        center_freq_mhz=f,
                        bandwidth_khz=25.0,
                        power_dbm=round(noise, 1),
                        noise_floor_dbm=-90.0,
                        snr_db=round(noise - (-90.0), 1),
                        is_carrier_burst=False,
                        band_label="Ambient Baseline"
                    )

            with self._lock:
                self._buffer.extend(obs_list)

            time.sleep(1.0)

    def stop(self) -> None:
        self.is_running = False

    def poll(self) -> List[RawObservation]:
        with self._lock:
            items = list(self._buffer)
            self._buffer.clear()
            return items

    def get_spectrum_bins(self) -> List[SpectrumBin]:
        with self._lock:
            return sorted(self._bins.values(), key=lambda b: b.center_freq_mhz)

    def get_fix(self) -> GeoFix:
        return self.current_fix
