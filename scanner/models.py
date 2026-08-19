"""Core data structures and models for the Scanner project."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple


class ModuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    STANDBY = "STANDBY"
    INACTIVE = "INACTIVE"
    ERROR = "ERROR"


class SignalTrend(str, Enum):
    APPROACHING = "APPROACHING"      # RSSI increasing rapidly (dRSSI/dt > +0.8 dB/s)
    CO_TRAVELING = "CO_TRAVELING"    # RSSI steady with low variance (sigma < 2.5 dB, dur > 10s)
    RECEDING = "RECEDING"            # RSSI decreasing rapidly (dRSSI/dt < -0.8 dB/s)
    STATIONARY = "STATIONARY"        # Low fluctuations at stationary speed or distant baseline
    UNKNOWN = "UNKNOWN"


class AntennaPosition(str, Enum):
    FRONT = "FRONT"                  # Front antenna / adapter (e.g. hci0 or SDR Front)
    REAR = "REAR"                    # Rear antenna / adapter (e.g. hci1 or SDR Rear)
    OMNI = "OMNI"                    # Single omni-directional antenna


class SpatialBearing(str, Enum):
    AHEAD = "AHEAD"                  # Delta RSSI (Front - Rear) > +4.0 dB
    BEHIND = "BEHIND"                # Delta RSSI (Front - Rear) < -4.0 dB
    ALONGSIDE = "ALONGSIDE"          # Delta RSSI within +/- 4.0 dB at strong signal
    OMNI = "OMNI"                    # Single antenna / indeterminate direction


class SensorType(str, Enum):
    BLUETOOTH = "BLUETOOTH"
    WIFI = "WIFI"
    SDR_RF = "SDR_RF"
    GPS = "GPS"
    MOCK = "MOCK"


@dataclass
class ModuleHealth:
    sensor: SensorType
    status: ModuleStatus
    display_name: str
    diagnostic_reason: str
    hardware_detected: bool = False
    required_device: str = ""
    activation_hint: str = ""
    last_probe_time: datetime = field(default_factory=datetime.now)


@dataclass
class GeoFix:
    latitude: float = 0.0
    longitude: float = 0.0
    speed_kmh: float = 0.0
    heading_deg: float = 0.0
    altitude_m: float = 0.0
    has_fix: bool = False
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class RawObservation:
    sensor: SensorType
    identifier: str           # MAC, BSSID, or frequency string (e.g. "386.250MHz")
    rssi_dbm: float
    antenna_pos: AntennaPosition = AntennaPosition.OMNI
    name_or_ssid: str = ""
    channel_or_freq: str = ""
    vendor: str = "Unknown"
    is_mobile_hotspot: bool = False
    is_randomized_mac: bool = False
    raw_payload_info: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class TrackedEntity:
    identifier: str
    sensor: SensorType
    name_or_ssid: str
    vendor: str
    first_seen: datetime
    last_seen: datetime
    rssi_history: List[Tuple[float, float]] = field(default_factory=list)  # (timestamp_sec, rssi_dbm)
    current_rssi: float = -100.0
    peak_rssi: float = -100.0
    front_rssi: float = -100.0
    rear_rssi: float = -100.0
    delta_rssi: float = 0.0        # (front_rssi - rear_rssi) in dB
    bearing: SpatialBearing = SpatialBearing.OMNI
    rssi_slope: float = 0.0        # dRSSI/dt in dB/sec
    rssi_variance: float = 0.0     # standard deviation of RSSI in current window
    trend: SignalTrend = SignalTrend.UNKNOWN
    is_co_traveling: bool = False
    is_mobile_hotspot: bool = False
    hit_count: int = 0


@dataclass
class SpectrumBin:
    center_freq_mhz: float
    bandwidth_khz: float
    power_dbm: float
    noise_floor_dbm: float
    snr_db: float
    is_carrier_burst: bool = False
    band_label: str = ""
    last_updated: datetime = field(default_factory=datetime.now)


@dataclass
class FeatureScore:
    name: str
    category: str
    raw_value: str
    weight: float
    points: float
    description: str


@dataclass
class ClassificationResult:
    probability_pct: float
    risk_level: str               # "LOW", "ELEVATED", "HIGH", "CRITICAL"
    total_score: float
    features: List[FeatureScore]
    summary_verdict: str
    timestamp: datetime = field(default_factory=datetime.now)
