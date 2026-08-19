"""Wi-Fi & Mobile Hotspot Collector for Linux (nmcli / iw / wireless tools)."""

import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime
from typing import List, Optional
from scanner.collectors.base import BaseCollector
from scanner.models import ModuleHealth, ModuleStatus, RawObservation, SensorType


class WiFiCollector(BaseCollector):
    def __init__(self, interface: Optional[str] = None):
        super().__init__(SensorType.WIFI, "Wi-Fi (802.11 Monitor)")
        self.interface = interface
        self._buffer: List[RawObservation] = []
        self._lock = threading.Lock()
        self._worker_thread: Optional[threading.Thread] = None

    def _find_wifi_interfaces(self) -> List[str]:
        interfaces = []
        net_dir = "/sys/class/net"
        if os.path.exists(net_dir):
            for iface in os.listdir(net_dir):
                # Wireless interfaces usually have a 'wireless' directory or 'phy80211' subsystem
                if os.path.exists(os.path.join(net_dir, iface, "wireless")) or os.path.exists(os.path.join(net_dir, iface, "phy80211")):
                    interfaces.append(iface)
        return interfaces

    def probe_hardware(self) -> ModuleHealth:
        wifi_ifaces = self._find_wifi_interfaces()
        has_nmcli = shutil.which("nmcli") is not None
        has_iw = shutil.which("iw") is not None

        if not wifi_ifaces:
            self.health = ModuleHealth(
                sensor=self.sensor_type,
                status=ModuleStatus.INACTIVE,
                display_name=self.display_name,
                diagnostic_reason="No 802.11 wireless network interfaces found.",
                hardware_detected=False,
                required_device="USB Wi-Fi adapter with Linux driver",
                activation_hint="Connect a USB Wi-Fi dongle (e.g. MT7612U, RTL8812AU, or Atheros AR9271)."
            )
            return self.health

        selected_iface = self.interface or wifi_ifaces[0]
        self.interface = selected_iface
        self.display_name = f"Wi-Fi ({selected_iface})"

        if not has_nmcli and not has_iw:
            self.health = ModuleHealth(
                sensor=self.sensor_type,
                status=ModuleStatus.STANDBY,
                display_name=self.display_name,
                diagnostic_reason="Neither 'nmcli' nor 'iw' tools were found in PATH.",
                hardware_detected=True,
                required_device="NetworkManager or iw package",
                activation_hint="Install NetworkManager ('sudo pacman -S networkmanager') or iw."
            )
            return self.health

        self.health = ModuleHealth(
            sensor=self.sensor_type,
            status=ModuleStatus.ACTIVE,
            display_name=self.display_name,
            diagnostic_reason=f"Wireless device '{selected_iface}' ready for beacon/probe scanning.",
            hardware_detected=True,
            required_device=selected_iface,
            activation_hint="Active and ready to scan nearby APs, beacons, and mobile hotspots."
        )
        return self.health

    def start(self) -> bool:
        probe = self.probe_hardware()
        if probe.status != ModuleStatus.ACTIVE:
            return False

        self.is_running = True
        self._worker_thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._worker_thread.start()
        return True

    def _scan_loop(self):
        hotspot_patterns = [
            re.compile(r"iphone", re.I),
            re.compile(r"androidap", re.I),
            re.compile(r"pixel[_\s]?\d", re.I),
            re.compile(r"galaxy[_\s]?", re.I),
            re.compile(r"huawei", re.I),
            re.compile(r"hotspot", re.I),
            re.compile(r"direct-", re.I),
        ]

        while self.is_running:
            try:
                # Use nmcli for non-disruptive scanning
                cmd = ["nmcli", "-t", "-f", "BSSID,SSID,SIGNAL,FREQ,CHAN,SECURITY", "device", "wifi", "list", "--rescan", "auto"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=4.0)
                
                if res.returncode == 0:
                    lines = res.stdout.strip().split("\n")
                    new_obs = []
                    for line in lines:
                        if not line.strip():
                            continue
                        # Unescape nmcli colon-separated output
                        # Format: BSSID:SSID:SIGNAL:FREQ:CHAN:SECURITY
                        parts = line.split(":")
                        if len(parts) >= 6:
                            bssid = ":".join(parts[0:6]).upper()
                            rest = parts[6:]
                            ssid = rest[0] if len(rest) > 0 else ""
                            signal_str = rest[1] if len(rest) > 1 else "50"
                            freq_str = rest[2] if len(rest) > 2 else "2400 MHz"
                            chan_str = rest[3] if len(rest) > 3 else "1"

                            try:
                                signal_pct = float(signal_str)
                                # Approximate dBm: 100% -> -40 dBm, 0% -> -100 dBm
                                rssi_dbm = (signal_pct / 2.0) - 100.0
                            except ValueError:
                                rssi_dbm = -75.0

                            is_hotspot = any(p.search(ssid) for p in hotspot_patterns)

                            new_obs.append(RawObservation(
                                sensor=SensorType.WIFI,
                                identifier=bssid,
                                rssi_dbm=rssi_dbm,
                                name_or_ssid=ssid or "[Hidden SSID]",
                                channel_or_freq=f"{freq_str} (Ch {chan_str})",
                                vendor="Mobile Hotspot" if is_hotspot else "Access Point",
                                is_mobile_hotspot=is_hotspot,
                                raw_payload_info=line
                            ))

                    with self._lock:
                        self._buffer.extend(new_obs)

            except Exception:
                pass

            time.sleep(2.5)

    def stop(self) -> None:
        self.is_running = False

    def poll(self) -> List[RawObservation]:
        with self._lock:
            items = list(self._buffer)
            self._buffer.clear()
            return items
