"""Unit tests for Hardware Probing and Dashboard Rendering."""

import unittest
from scanner.collectors.bluetooth_collector import BluetoothCollector
from scanner.collectors.gps_collector import GPSCollector
from scanner.collectors.mock_collector import MockCollector
from scanner.collectors.sdr_collector import SDRCollector
from scanner.collectors.wifi_collector import WiFiCollector
from scanner.engine.classifier import SensorFusionClassifier
from scanner.engine.temporal_tracker import TemporalTracker
from scanner.models import GeoFix, ModuleStatus
from scanner.ui.dashboard import TerminalDashboard


class TestCollectorsAndUI(unittest.TestCase):
    def test_collectors_hardware_probing_graceful_degradation(self):
        """Verify probing does not crash on missing physical hardware and returns structured status."""
        bt = BluetoothCollector()
        wifi = WiFiCollector()
        sdr = SDRCollector()
        gps = GPSCollector()

        bt_h = bt.probe_hardware()
        wifi_h = wifi.probe_hardware()
        sdr_h = sdr.probe_hardware()
        gps_h = gps.probe_hardware()

        self.assertIn(bt_h.status, (ModuleStatus.ACTIVE, ModuleStatus.STANDBY, ModuleStatus.INACTIVE, ModuleStatus.ERROR))
        self.assertIn(wifi_h.status, (ModuleStatus.ACTIVE, ModuleStatus.STANDBY, ModuleStatus.INACTIVE, ModuleStatus.ERROR))
        self.assertIn(sdr_h.status, (ModuleStatus.ACTIVE, ModuleStatus.STANDBY, ModuleStatus.INACTIVE, ModuleStatus.ERROR))
        self.assertIn(gps_h.status, (ModuleStatus.ACTIVE, ModuleStatus.STANDBY, ModuleStatus.INACTIVE, ModuleStatus.ERROR))

        if sdr_h.status == ModuleStatus.INACTIVE:
            self.assertGreater(len(sdr_h.activation_hint), 5)
            self.assertGreater(len(sdr_h.diagnostic_reason), 5)

        if gps_h.status == ModuleStatus.INACTIVE:
            self.assertGreater(len(gps_h.activation_hint), 5)

    def test_mock_collector_scenario_stream(self):
        sim = MockCollector(scenario="patrol_approach")
        health = sim.probe_hardware()
        self.assertEqual(health.status, ModuleStatus.ACTIVE)

        sim.start()
        obs = sim.poll()
        bins = sim.get_spectrum_bins()
        fix = sim.get_fix()

        self.assertTrue(fix.has_fix)
        self.assertGreater(len(bins), 0)
        sim.stop()

    def test_dashboard_render_output(self):
        dashboard = TerminalDashboard()
        tracker = TemporalTracker()
        classifier = SensorFusionClassifier()
        sim = MockCollector(scenario="patrol_approach")
        sim.start()
        
        obs = sim.poll()
        fix = sim.get_fix()
        tracker.update(obs, fix.speed_kmh)
        entities = tracker.get_active_entities()
        bins = sim.get_spectrum_bins()
        result = classifier.evaluate(entities, bins, fix)
        sim.stop()

        renderable = dashboard.render_layout(
            geo_fix=fix,
            is_mock=True,
            scenario_name="patrol_approach",
            health_list=[sim.health],
            result=result,
            entities=entities,
            bins=bins
        )

        self.assertIsNotNone(renderable)


if __name__ == "__main__":
    unittest.main()
