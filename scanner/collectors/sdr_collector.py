"""RTL-SDR & Radio Frequency Spectrum Collector (rtl_power / rtl_sdr / pyrtlsdr)."""

import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional
from scanner.collectors.base import BaseCollector
from scanner.models import ModuleHealth, ModuleStatus, RawObservation, SensorType, SpectrumBin


class SDRCollector(BaseCollector):
    # Standard European ETSI / CEPT & ČTÚ spectrum target bands
    TARGET_BANDS = [
        {"name": "TETRA/PEGAS Downlink (EU)", "start_mhz": 390.0, "end_mhz": 395.0, "step_khz": 25.0},
        {"name": "TETRA/PEGAS Uplink (EU)", "start_mhz": 380.0, "end_mhz": 385.0, "step_khz": 25.0},
        {"name": "ISM/SRD Europe (433)", "start_mhz": 433.0, "end_mhz": 435.0, "step_khz": 25.0},
        {"name": "PMR446 Europe", "start_mhz": 446.0, "end_mhz": 446.2, "step_khz": 12.5},
        {"name": "SRD/IoT EU868", "start_mhz": 868.0, "end_mhz": 870.0, "step_khz": 25.0},
    ]

    def __init__(self, target_band_index: int = 0):
        super().__init__(SensorType.SDR_RF, "RTL-SDR (RF Spectrum)")
        self.target_band_index = target_band_index
        self._buffer: List[RawObservation] = []
        self._bins: Dict[float, SpectrumBin] = {}
        self._lock = threading.Lock()
        self._worker_thread: Optional[threading.Thread] = None

    def _check_usb_devices(self) -> bool:
        """Scan sysfs for Realtek RTL2832U USB Vendor/Product IDs."""
        usb_dir = "/sys/bus/usb/devices"
        if not os.path.exists(usb_dir):
            return False

        rtl_vid_pids = {("0bda", "2838"), ("0bda", "2832"), ("0403", "6001")}
        for device in os.listdir(usb_dir):
            dev_path = os.path.join(usb_dir, device)
            id_vendor_path = os.path.join(dev_path, "idVendor")
            id_product_path = os.path.join(dev_path, "idProduct")
            if os.path.exists(id_vendor_path) and os.path.exists(id_product_path):
                try:
                    with open(id_vendor_path, "r") as f:
                        vid = f.read().strip().lower()
                    with open(id_product_path, "r") as f:
                        pid = f.read().strip().lower()
                    if (vid, pid) in rtl_vid_pids:
                        return True
                except Exception:
                    pass
        return False

    def probe_hardware(self) -> ModuleHealth:
        has_rtl_power = shutil.which("rtl_power") is not None
        has_rtl_sdr = shutil.which("rtl_sdr") is not None
        has_usb_device = self._check_usb_devices()

        if not has_usb_device:
            self.health = ModuleHealth(
                sensor=self.sensor_type,
                status=ModuleStatus.INACTIVE,
                display_name=self.display_name,
                diagnostic_reason="No RTL2832U SDR USB dongle detected on USB bus.",
                hardware_detected=False,
                required_device="RTL-SDR Blog V3/V4 or compatible receiver",
                activation_hint="Plug in an RTL-SDR dongle to activate RF spectrum analysis."
            )
            return self.health

        if not has_rtl_power and not has_rtl_sdr:
            self.health = ModuleHealth(
                sensor=self.sensor_type,
                status=ModuleStatus.STANDBY,
                display_name=self.display_name,
                diagnostic_reason="RTL-SDR USB dongle attached, but 'rtl_power' CLI tool is missing.",
                hardware_detected=True,
                required_device="rtl-sdr package",
                activation_hint="Install RTL-SDR utilities: 'sudo pacman -S rtl-sdr' or 'sudo apt install rtl-sdr'."
            )
            return self.health

        self.health = ModuleHealth(
            sensor=self.sensor_type,
            status=ModuleStatus.ACTIVE,
            display_name="RTL-SDR (TETRA/UHF Scanner)",
            diagnostic_reason="RTL-SDR hardware online. Ready to sweep 380–400 MHz & 433–868 MHz.",
            hardware_detected=True,
            required_device="RTL2832U Dongle",
            activation_hint="Active and sweeping spectrum for carrier power bursts."
        )
        return self.health

    def start(self) -> bool:
        probe = self.probe_hardware()
        if probe.status != ModuleStatus.ACTIVE:
            return False

        self.is_running = True
        self._worker_thread = threading.Thread(target=self._sweep_loop, daemon=True)
        self._worker_thread.start()
        return True

    def _sweep_loop(self):
        band = self.TARGET_BANDS[self.target_band_index]
        start_m = f"{int(band['start_mhz'])}M"
        end_m = f"{int(band['end_mhz'])}M"
        step_k = f"{int(band['step_khz'])}k"

        while self.is_running:
            try:
                # Run single 2-second sweep integration
                cmd = ["rtl_power", "-f", f"{start_m}:{end_m}:{step_k}", "-i", "2", "-1"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=5.0)
                if res.returncode == 0:
                    for line in res.stdout.strip().split("\n"):
                        # Format: date, time, Hz_low, Hz_high, Hz_step, sample_count, dBm_1, dBm_2...
                        parts = [p.strip() for p in line.split(",")]
                        if len(parts) > 6:
                            hz_low = float(parts[2])
                            hz_step = float(parts[4])
                            dbm_values = [float(x) for x in parts[6:]]

                            # Calculate noise baseline as 25th percentile
                            sorted_dbm = sorted(dbm_values)
                            baseline_dbm = sorted_dbm[len(sorted_dbm) // 4] if sorted_dbm else -90.0

                            for i, val in enumerate(dbm_values):
                                freq_mhz = (hz_low + (i * hz_step)) / 1e6
                                snr = val - baseline_dbm
                                is_burst = snr > 12.0  # Spike 12dB over noise floor

                                bin_obj = SpectrumBin(
                                    center_freq_mhz=round(freq_mhz, 3),
                                    bandwidth_khz=hz_step / 1000.0,
                                    power_dbm=val,
                                    noise_floor_dbm=baseline_dbm,
                                    snr_db=snr,
                                    is_carrier_burst=is_burst,
                                    band_label=band["name"]
                                )
                                with self._lock:
                                    self._bins[bin_obj.center_freq_mhz] = bin_obj

                                    if is_burst:
                                        self._buffer.append(RawObservation(
                                            sensor=SensorType.SDR_RF,
                                            identifier=f"{freq_mhz:.3f}MHz",
                                            rssi_dbm=val,
                                            name_or_ssid=f"RF Burst (+{snr:.1f}dB SNR)",
                                            channel_or_freq=f"{freq_mhz:.3f} MHz",
                                            vendor=f"Spectrum Peak ({band['name']})",
                                            raw_payload_info=f"Power: {val:.1f}dBm, SNR: {snr:.1f}dB"
                                        ))
            except Exception:
                pass

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
