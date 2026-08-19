"""Bluetooth & BLE Collector for Linux (BlueZ / bluetoothctl / DBus)."""

import os
import re
import shutil
import subprocess
import threading
from datetime import datetime
from typing import List, Optional
from scanner.collectors.base import BaseCollector
from scanner.models import ModuleHealth, ModuleStatus, RawObservation, SensorType


class BluetoothCollector(BaseCollector):
    def __init__(self, interface: str = "hci0"):
        super().__init__(SensorType.BLUETOOTH, f"Bluetooth ({interface})")
        self.interface = interface
        self._proc: Optional[subprocess.Popen] = None
        self._buffer: List[RawObservation] = []
        self._lock = threading.Lock()
        self._reader_thread: Optional[threading.Thread] = None

    def probe_hardware(self) -> ModuleHealth:
        # Check /sys/class/bluetooth/ for interfaces
        bt_sys = "/sys/class/bluetooth"
        has_sys_device = False
        available_ifaces = []

        if os.path.exists(bt_sys):
            available_ifaces = os.listdir(bt_sys)
            has_sys_device = len(available_ifaces) > 0

        # Check for bluetoothctl binary
        has_tool = shutil.which("bluetoothctl") is not None

        if not has_tool:
            self.health = ModuleHealth(
                sensor=self.sensor_type,
                status=ModuleStatus.INACTIVE,
                display_name=self.display_name,
                diagnostic_reason="`bluetoothctl` utility not found in system PATH.",
                hardware_detected=False,
                required_device="BlueZ package",
                activation_hint="Install BlueZ: 'sudo pacman -S bluez bluez-utils' or 'sudo apt install bluez'."
            )
            return self.health

        if not has_sys_device:
            self.health = ModuleHealth(
                sensor=self.sensor_type,
                status=ModuleStatus.INACTIVE,
                display_name=self.display_name,
                diagnostic_reason=f"No Bluetooth controller found at {bt_sys}.",
                hardware_detected=False,
                required_device="USB Bluetooth Dongle or built-in chip",
                activation_hint="Plug in a USB Bluetooth 5.0 dongle (CSR8510, Realtek, or Intel)."
            )
            return self.health

        # Probe controller state
        try:
            res = subprocess.run(
                ["bluetoothctl", "show"],
                capture_output=True,
                text=True,
                timeout=2.0
            )
            output = res.stdout
            if "Powered: yes" in output:
                self.health = ModuleHealth(
                    sensor=self.sensor_type,
                    status=ModuleStatus.ACTIVE,
                    display_name=f"Bluetooth ({available_ifaces[0] if available_ifaces else self.interface})",
                    diagnostic_reason=f"Controller online and ready. Subsystem: {', '.join(available_ifaces)}.",
                    hardware_detected=True,
                    required_device="BlueZ Controller",
                    activation_hint="Active and ready to scan BLE advertisements."
                )
            elif "Powered: no" in output:
                self.health = ModuleHealth(
                    sensor=self.sensor_type,
                    status=ModuleStatus.STANDBY,
                    display_name=self.display_name,
                    diagnostic_reason="Bluetooth controller found but currently powered off.",
                    hardware_detected=True,
                    required_device="Powered Controller",
                    activation_hint="Power on adapter: 'bluetoothctl power on' or 'rfkill unblock bluetooth'."
                )
            else:
                self.health = ModuleHealth(
                    sensor=self.sensor_type,
                    status=ModuleStatus.STANDBY,
                    display_name=self.display_name,
                    diagnostic_reason="Bluetooth daemon not responding to query.",
                    hardware_detected=True,
                    required_device="Active bluetooth.service",
                    activation_hint="Start BlueZ daemon: 'sudo systemctl start bluetooth.service'."
                )
        except Exception as e:
            self.health = ModuleHealth(
                sensor=self.sensor_type,
                status=ModuleStatus.ERROR,
                display_name=self.display_name,
                diagnostic_reason=f"Failed querying controller: {str(e)}",
                hardware_detected=has_sys_device,
                required_device="Operational BlueZ",
                activation_hint="Check bluetooth daemon logs: 'journalctl -u bluetooth -n 20'."
            )

        return self.health

    def start(self) -> bool:
        probe = self.probe_hardware()
        if probe.status != ModuleStatus.ACTIVE:
            return False

        try:
            # Start bluetoothctl in scan mode
            self._proc = subprocess.Popen(
                ["bluetoothctl", "--", "scan", "on"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            self.is_running = True
            self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._reader_thread.start()
            return True
        except Exception as e:
            self.health.status = ModuleStatus.ERROR
            self.health.diagnostic_reason = f"Failed to start scanner: {e}"
            return False

    def _read_loop(self):
        # Parses lines like:
        # [CHG] Device AA:BB:CC:DD:EE:FF RSSI: -65
        # [NEW] Device AA:BB:CC:DD:EE:FF Galaxy Watch4
        # [CHG] Device AA:BB:CC:DD:EE:FF TxPower: 12
        mac_regex = re.compile(r"([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})")
        rssi_regex = re.compile(r"RSSI:\s*(-?\d+)")

        if not self._proc or not self._proc.stdout:
            return

        for line in self._proc.stdout:
            if not self.is_running:
                break
            mac_match = mac_regex.search(line)
            if mac_match:
                mac = mac_match.group(1).upper()
                rssi_match = rssi_regex.search(line)
                rssi = float(rssi_match.group(1)) if rssi_match else -75.0
                
                # Check for device name
                name = ""
                if "Device " + mac in line and "RSSI:" not in line and "TxPower:" not in line:
                    parts = line.split(mac, 1)
                    if len(parts) > 1:
                        name = parts[1].strip()

                # Basic OUI resolution or randomized MAC detection
                # In BLE, if the first byte's 2nd least significant bit is set, it's a locally administered / randomized MAC
                first_octet = int(mac.split(":")[0], 16)
                is_random = (first_octet & 0x02) != 0

                obs = RawObservation(
                    sensor=SensorType.BLUETOOTH,
                    identifier=mac,
                    rssi_dbm=rssi,
                    name_or_ssid=name,
                    channel_or_freq="2.4GHz BLE",
                    vendor="Randomized Address" if is_random else "Registered OUI",
                    is_randomized_mac=is_random,
                    raw_payload_info=line.strip()
                )
                with self._lock:
                    self._buffer.append(obs)

    def stop(self) -> None:
        self.is_running = False
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=1.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    def poll(self) -> List[RawObservation]:
        with self._lock:
            items = list(self._buffer)
            self._buffer.clear()
            return items
