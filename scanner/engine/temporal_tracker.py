"""Temporal RSSI Tracking & Spatial Gradient Engine."""

import math
import time
from datetime import datetime
from typing import Dict, List, Optional
from scanner.models import AntennaPosition, RawObservation, SignalTrend, SpatialBearing, TrackedEntity


class TemporalTracker:
    def __init__(self, window_sec: float = 20.0, stale_timeout_sec: float = 35.0):
        self.window_sec = window_sec
        self.stale_timeout_sec = stale_timeout_sec
        self.entities: Dict[str, TrackedEntity] = {}

    def update(self, observations: List[RawObservation], current_speed_kmh: float = 0.0) -> None:
        now_ts = time.time()
        now_dt = datetime.now()

        for obs in observations:
            entity_id = obs.identifier
            if entity_id not in self.entities:
                new_entity = TrackedEntity(
                    identifier=entity_id,
                    sensor=obs.sensor,
                    name_or_ssid=obs.name_or_ssid,
                    vendor=obs.vendor,
                    first_seen=now_dt,
                    last_seen=now_dt,
                    rssi_history=[(now_ts, obs.rssi_dbm)],
                    current_rssi=obs.rssi_dbm,
                    peak_rssi=obs.rssi_dbm,
                    is_mobile_hotspot=obs.is_mobile_hotspot,
                    hit_count=1
                )
                if obs.antenna_pos == AntennaPosition.FRONT:
                    new_entity.front_rssi = obs.rssi_dbm
                elif obs.antenna_pos == AntennaPosition.REAR:
                    new_entity.rear_rssi = obs.rssi_dbm
                self.entities[entity_id] = new_entity
            else:
                entity = self.entities[entity_id]
                entity.last_seen = now_dt
                entity.current_rssi = obs.rssi_dbm
                entity.peak_rssi = max(entity.peak_rssi, obs.rssi_dbm)
                entity.hit_count += 1
                if obs.name_or_ssid and not entity.name_or_ssid:
                    entity.name_or_ssid = obs.name_or_ssid
                if obs.is_mobile_hotspot:
                    entity.is_mobile_hotspot = True

                if obs.antenna_pos == AntennaPosition.FRONT:
                    entity.front_rssi = obs.rssi_dbm
                elif obs.antenna_pos == AntennaPosition.REAR:
                    entity.rear_rssi = obs.rssi_dbm

                entity.rssi_history.append((now_ts, obs.rssi_dbm))

        # Filter sliding windows & compute math gradients
        cutoff_ts = now_ts - self.window_sec

        to_delete = []
        for entity_id, entity in self.entities.items():
            # Evict dead entities
            if (now_ts - entity.last_seen.timestamp()) > self.stale_timeout_sec:
                to_delete.append(entity_id)
                continue

            # Trim history to sliding window
            entity.rssi_history = [
                (t, r) for (t, r) in entity.rssi_history if t >= cutoff_ts
            ]

            n = len(entity.rssi_history)
            if n < 2:
                entity.rssi_slope = 0.0
                entity.rssi_variance = 0.0
                entity.trend = SignalTrend.UNKNOWN
                entity.is_co_traveling = False
                continue

            # 1. Numerically stable linear regression: dRSSI / dt
            # Normalize timestamps relative to the first entry in the window
            t0 = entity.rssi_history[0][0]
            rel_history = [(t - t0, r) for t, r in entity.rssi_history]

            sum_t = sum(t for t, _ in rel_history)
            sum_r = sum(r for _, r in rel_history)
            sum_t2 = sum(t * t for t, _ in rel_history)
            sum_tr = sum(t * r for t, r in rel_history)

            denom = (n * sum_t2) - (sum_t * sum_t)
            if abs(denom) > 1e-6:
                slope = ((n * sum_tr) - (sum_t * sum_r)) / denom
            else:
                slope = 0.0
            entity.rssi_slope = round(slope, 3)

            # 2. Standard deviation of RSSI
            mean_r = sum_r / n
            var = sum((r - mean_r) ** 2 for _, r in rel_history) / n
            std_dev = math.sqrt(var)
            entity.rssi_variance = round(std_dev, 2)

            # 3. Spatial Bearing Calculation (Differential Front - Rear RSSI)
            if entity.front_rssi > -95.0 and entity.rear_rssi > -95.0:
                entity.delta_rssi = round(entity.front_rssi - entity.rear_rssi, 1)
                if entity.delta_rssi >= 4.0:
                    entity.bearing = SpatialBearing.AHEAD
                elif entity.delta_rssi <= -4.0:
                    entity.bearing = SpatialBearing.BEHIND
                else:
                    entity.bearing = SpatialBearing.ALONGSIDE
            elif entity.front_rssi > -95.0 and entity.rear_rssi <= -95.0:
                entity.bearing = SpatialBearing.AHEAD
                entity.delta_rssi = round(entity.front_rssi - (-95.0), 1)
            elif entity.rear_rssi > -95.0 and entity.front_rssi <= -95.0:
                entity.bearing = SpatialBearing.BEHIND
                entity.delta_rssi = round(-95.0 - entity.rear_rssi, 1)
            else:
                entity.bearing = SpatialBearing.OMNI
                entity.delta_rssi = 0.0

            # 4. Time span in window
            time_span = rel_history[-1][0] - rel_history[0][0]

            # 5. Trend classification
            if slope > 0.75 and entity.current_rssi > -78.0:
                entity.trend = SignalTrend.APPROACHING
                entity.is_co_traveling = False
            elif slope < -0.75:
                entity.trend = SignalTrend.RECEDING
                entity.is_co_traveling = False
            elif time_span >= 7.0 and std_dev < 2.5 and entity.current_rssi > -65.0 and current_speed_kmh > 20.0:
                # Signal is strong, stable, and vehicle is moving fast -> transmitter is moving with us
                entity.trend = SignalTrend.CO_TRAVELING
                entity.is_co_traveling = True
            elif current_speed_kmh < 10.0:
                entity.trend = SignalTrend.STATIONARY
                entity.is_co_traveling = False
            else:
                entity.trend = SignalTrend.UNKNOWN
                entity.is_co_traveling = False

        for dead_id in to_delete:
            del self.entities[dead_id]

    def get_active_entities(self) -> List[TrackedEntity]:
        return sorted(self.entities.values(), key=lambda e: e.current_rssi, reverse=True)
