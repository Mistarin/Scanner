"""Unit tests for Temporal Tracker and Classifier Engine."""

import time
import unittest
from datetime import datetime
from scanner.engine.classifier import SensorFusionClassifier
from scanner.engine.temporal_tracker import TemporalTracker
from scanner.models import (
    AntennaPosition,
    GeoFix,
    RawObservation,
    SensorType,
    SignalTrend,
    SpatialBearing,
    SpectrumBin,
)


class TestEngine(unittest.TestCase):
    def test_temporal_tracker_approaching_gradient(self):
        tracker = TemporalTracker(window_sec=15.0)
        now = time.time()

        # Seed entity
        obs = RawObservation(
            sensor=SensorType.BLUETOOTH,
            identifier="AA:BB:CC:DD:EE:01",
            rssi_dbm=-50.0,
            name_or_ssid="Approaching_Target",
            timestamp=datetime.now()
        )
        tracker.update([obs], current_speed_kmh=50.0)

        # Explicitly set history with +5.0 dB/s slope (-80dBm to -50dBm over 6s)
        tracker.entities["AA:BB:CC:DD:EE:01"].rssi_history = [
            (now - (4 - i) * 1.5, -80.0 + (i * 7.5)) for i in range(5)
        ]

        tracker.update([], current_speed_kmh=50.0)
        entity = tracker.entities["AA:BB:CC:DD:EE:01"]
        
        self.assertGreater(entity.rssi_slope, 0.75)
        self.assertEqual(entity.trend, SignalTrend.APPROACHING)
        self.assertFalse(entity.is_co_traveling)

    def test_temporal_tracker_co_traveling(self):
        tracker = TemporalTracker(window_sec=20.0)
        now = time.time()

        # Seed entity
        obs = RawObservation(
            sensor=SensorType.BLUETOOTH,
            identifier="11:22:33:44:55:66",
            rssi_dbm=-48.0,
            name_or_ssid="Pacing_Target",
            timestamp=datetime.now()
        )
        tracker.update([obs], current_speed_kmh=70.0)

        # Explicitly set history with low variance over 10.5s
        tracker.entities["11:22:33:44:55:66"].rssi_history = [
            (now - (7 - i) * 1.5, -48.0 + (0.5 if i % 2 == 0 else -0.5)) for i in range(8)
        ]

        tracker.update([], current_speed_kmh=70.0)
        entity = tracker.entities["11:22:33:44:55:66"]

        self.assertTrue(entity.is_co_traveling)
        self.assertEqual(entity.trend, SignalTrend.CO_TRAVELING)
        self.assertLess(entity.rssi_variance, 2.5)

    def test_classifier_patrol_scoring(self):
        classifier = SensorFusionClassifier()
        tracker = TemporalTracker()
        now = time.time()

        obs = RawObservation(
            sensor=SensorType.BLUETOOTH,
            identifier="AA:BB:CC:00:00:01",
            rssi_dbm=-45.0,
            name_or_ssid="Sepura_SC20_TETRA",
            vendor="Sepura PLC",
            timestamp=datetime.now()
        )
        tracker.update([obs], current_speed_kmh=80.0)
        tracker.entities["AA:BB:CC:00:00:01"].rssi_history = [
            (now - (7 - i) * 1.5, -45.0) for i in range(8)
        ]

        ambient_obs = [
            RawObservation(
                sensor=SensorType.BLUETOOTH,
                identifier=f"FF:EE:DD:00:00:{i:02X}",
                rssi_dbm=-65.0,
                name_or_ssid=f"Device_{i}",
                vendor="Randomized Address"
            )
            for i in range(12)
        ]
        tracker.update(ambient_obs, current_speed_kmh=80.0)

        rf_bin = SpectrumBin(
            center_freq_mhz=391.250,
            bandwidth_khz=25.0,
            power_dbm=-55.0,
            noise_floor_dbm=-85.0,
            snr_db=30.0,
            is_carrier_burst=True,
            band_label="TETRA/PEGAS Downlink (EU)"
        )

        geo_fix = GeoFix(speed_kmh=80.0, has_fix=True)
        entities = tracker.get_active_entities()
        
        result = classifier.evaluate(entities, [rf_bin], geo_fix)

        self.assertGreaterEqual(result.probability_pct, 80.0)
        self.assertEqual(result.risk_level, "CRITICAL")
        feature_names = [f.name for f in result.features]
        self.assertIn("BLE Cluster Density", feature_names)
        self.assertIn("Hardware Signature", feature_names)
        self.assertIn("RF Carrier Peak (TETRA/UHF)", feature_names)
        self.assertIn("Co-traveling RF Gradient", feature_names)

    def test_classifier_traffic_jam_dampener(self):
        classifier = SensorFusionClassifier()
        tracker = TemporalTracker()

        ambient_obs = [
            RawObservation(
                sensor=SensorType.BLUETOOTH,
                identifier=f"00:11:22:33:44:{i:02X}",
                rssi_dbm=-70.0,
                name_or_ssid=f"Phone_{i}",
                vendor="Generic Phone"
            )
            for i in range(15)
        ]
        tracker.update(ambient_obs, current_speed_kmh=5.0)
        
        geo_fix = GeoFix(speed_kmh=5.0, has_fix=True)
        result = classifier.evaluate(tracker.get_active_entities(), [], geo_fix)

        feature_names = [f.name for f in result.features]
        self.assertIn("Commuter Traffic Baseline", feature_names)
        self.assertLess(result.probability_pct, 30.0)

    def test_temporal_tracker_bidirectional_bearing(self):
        tracker = TemporalTracker()

        # Emitter approaching from behind (Rear = -45dBm, Front = -58dBm -> Delta = -13dB)
        obs_rear = RawObservation(
            sensor=SensorType.BLUETOOTH,
            identifier="BB:CC:DD:11:22:33",
            rssi_dbm=-45.0,
            antenna_pos=AntennaPosition.REAR,
            name_or_ssid="Rear_Target"
        )
        obs_front = RawObservation(
            sensor=SensorType.BLUETOOTH,
            identifier="BB:CC:DD:11:22:33",
            rssi_dbm=-58.0,
            antenna_pos=AntennaPosition.FRONT,
            name_or_ssid="Rear_Target"
        )
        tracker.update([obs_rear, obs_front], current_speed_kmh=60.0)
        entity = tracker.entities["BB:CC:DD:11:22:33"]

        self.assertEqual(entity.bearing, SpatialBearing.BEHIND)
        self.assertEqual(entity.delta_rssi, -13.0)

        # Emitter moves ahead (Front = -42dBm, Rear = -55dBm -> Delta = +13dB)
        obs_front_ahead = RawObservation(
            sensor=SensorType.BLUETOOTH,
            identifier="BB:CC:DD:11:22:33",
            rssi_dbm=-42.0,
            antenna_pos=AntennaPosition.FRONT
        )
        obs_rear_ahead = RawObservation(
            sensor=SensorType.BLUETOOTH,
            identifier="BB:CC:DD:11:22:33",
            rssi_dbm=-55.0,
            antenna_pos=AntennaPosition.REAR
        )
        tracker.update([obs_front_ahead, obs_rear_ahead], current_speed_kmh=60.0)
        entity = tracker.entities["BB:CC:DD:11:22:33"]

        self.assertEqual(entity.bearing, SpatialBearing.AHEAD)
        self.assertEqual(entity.delta_rssi, 13.0)


if __name__ == "__main__":
    unittest.main()
