"""GPS & Geolocation Collector (Serial NMEA / VK-172 / gpsd)."""

import glob
import os
import re
import threading
import time
from datetime import datetime
from typing import List, Optional
from scanner.collectors.base import BaseCollector
from scanner.models import GeoFix, ModuleHealth, ModuleStatus, RawObservation, SensorType


class GPSCollector(BaseCollector):
    def __init__(self, port_pattern: str = "/dev/ttyUSB*"):
        super().__init__(SensorType.GPS, "GPS / Geolocation")
        self.port_pattern = port_pattern
        self.active_port: Optional[str] = None
        self.current_fix = GeoFix(has_fix=False)
        self._lock = threading.Lock()
        self._worker_thread: Optional[threading.Thread] = None

    def probe_hardware(self) -> ModuleHealth:
        ports = glob.glob(self.port_pattern) + glob.glob("/dev/ttyACM*")
        
        if not ports:
            self.health = ModuleHealth(
                sensor=self.sensor_type,
                status=ModuleStatus.INACTIVE,
                display_name=self.display_name,
                diagnostic_reason="No USB serial GPS receivers detected in /dev/ttyUSB* or /dev/ttyACM*.",
                hardware_detected=False,
                required_device="USB GPS Module (e.g. VK-172 / u-blox / NMEA serial)",
                activation_hint="Connect a USB GPS dongle to enable speed-correlated RF tracking."
            )
            return self.health

        self.active_port = ports[0]
        self.display_name = f"GPS ({os.path.basename(self.active_port)})"

        self.health = ModuleHealth(
            sensor=self.sensor_type,
            status=ModuleStatus.ACTIVE,
            display_name=self.display_name,
            diagnostic_reason=f"Serial GPS module ready on {self.active_port} at 9600 baud.",
            hardware_detected=True,
            required_device=self.active_port,
            activation_hint="Active and parsing NMEA coordinates and velocity."
        )
        return self.health

    def start(self) -> bool:
        probe = self.probe_hardware()
        if probe.status != ModuleStatus.ACTIVE or not self.active_port:
            return False

        self.is_running = True
        self._worker_thread = threading.Thread(target=self._read_serial_loop, daemon=True)
        self._worker_thread.start()
        return True

    def _parse_nmea(self, line: str):
        # Parses $GPRMC or $GNRMC
        # $GPRMC,hhmmss.ss,A,llll.ll,a,yyyyy.yy,a,x.x,x.x,ddmmyy,,,a*hh
        if "$GPRMC" in line or "$GNRMC" in line:
            parts = line.split(",")
            if len(parts) >= 9:
                status = parts[2]
                if status == "A":  # Active fix
                    try:
                        # Speed over ground in knots -> km/h
                        speed_knots = float(parts[7]) if parts[7] else 0.0
                        speed_kmh = speed_knots * 1.852
                        heading_deg = float(parts[8]) if parts[8] else 0.0

                        # Parse latitude
                        lat_raw = parts[3]
                        lat_hemi = parts[4]
                        lat = 0.0
                        if lat_raw and len(lat_raw) >= 4:
                            lat_deg = float(lat_raw[:2])
                            lat_min = float(lat_raw[2:])
                            lat = lat_deg + (lat_min / 60.0)
                            if lat_hemi == "S":
                                lat = -lat

                        # Parse longitude
                        lon_raw = parts[5]
                        lon_hemi = parts[6]
                        lon = 0.0
                        if lon_raw and len(lon_raw) >= 5:
                            lon_deg = float(lon_raw[:3])
                            lon_min = float(lon_raw[3:])
                            lon = lon_deg + (lon_min / 60.0)
                            if lon_hemi == "W":
                                lon = -lon

                        with self._lock:
                            self.current_fix = GeoFix(
                                latitude=lat,
                                longitude=lon,
                                speed_kmh=round(speed_kmh, 1),
                                heading_deg=round(heading_deg, 1),
                                has_fix=True,
                                timestamp=datetime.now()
                            )
                    except Exception:
                        pass

    def _read_serial_loop(self):
        try:
            with open(self.active_port, "r", errors="ignore") as f:
                while self.is_running:
                    line = f.readline()
                    if line:
                        self._parse_nmea(line)
                    else:
                        time.sleep(0.1)
        except Exception:
            pass

    def stop(self) -> None:
        self.is_running = False

    def poll(self) -> List[RawObservation]:
        # GPS does not generate direct entity observations, it provides spatial context
        return []

    def get_fix(self) -> GeoFix:
        with self._lock:
            return self.current_fix
