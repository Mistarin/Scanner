"""Main CLI Entrypoint for the RF & Sensor-Fusion Scanner."""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import List
from rich.console import Console
from rich.live import Live

from scanner.audio import ProximityBeeper
from scanner.collectors.bluetooth_collector import BluetoothCollector
from scanner.collectors.gps_collector import GPSCollector
from scanner.collectors.mock_collector import MockCollector
from scanner.collectors.sdr_collector import SDRCollector
from scanner.collectors.wifi_collector import WiFiCollector
from scanner.engine.classifier import SensorFusionClassifier
from scanner.engine.temporal_tracker import TemporalTracker
from scanner.models import (
    ClassificationResult,
    GeoFix,
    ModuleHealth,
    ModuleStatus,
    RawObservation,
    SensorType,
    SpectrumBin,
)
from scanner.shopping_list import generate_shopping_list
from scanner.ui.dashboard import TerminalDashboard


def parse_args():
    parser = argparse.ArgumentParser(
        description="Passive RF, BLE, Wi-Fi & GPS Scanner with Sensor-Fusion Classifier.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 main.py                             # Run with live local hardware & audio beeper
  python3 main.py --mock                      # Run simulator with default patrol scenario
  python3 main.py --shopping-list             # Audit hardware and generate upgrade shopping list
  python3 main.py --mute                      # Mute audio proximity beeper
  python3 main.py --oneshot                   # Single snapshot diagnostic probe
  python3 main.py --log drive_01.jsonl        # Record drive data for ML calibration
        """
    )
    parser.add_argument("--mock", action="store_true", help="Enable synthetic RF/BLE simulation mode")
    parser.add_argument(
        "--scenario",
        default="patrol_approach",
        choices=["patrol_approach", "normal_highway", "city_traffic_jam", "stationary_radar"],
        help="Simulation scenario to execute when --mock is enabled"
    )
    parser.add_argument("--interval", type=float, default=1.0, help="UI refresh rate in seconds (default: 1.0)")
    parser.add_argument("--oneshot", action="store_true", help="Execute single diagnostic snapshot and exit")
    parser.add_argument("--shopping-list", action="store_true", help="Audit hardware and print/save upgrade shopping list")
    parser.add_argument("--mute", "--no-audio", action="store_true", help="Mute the proximity audio beeper")
    parser.add_argument("--log", type=str, default=None, help="Path to write JSONL telemetry stream")
    return parser.parse_args()


def log_telemetry(log_file: str, result: ClassificationResult, geo: GeoFix, obs_count: int):
    if not log_file:
        return
    try:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "probability_pct": result.probability_pct,
            "risk_level": result.risk_level,
            "total_score": result.total_score,
            "speed_kmh": geo.speed_kmh,
            "latitude": geo.latitude,
            "longitude": geo.longitude,
            "active_observations": obs_count,
            "features": [
                {"name": f.name, "points": f.points, "value": f.raw_value}
                for f in result.features
            ]
        }
        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def main():
    args = parse_args()

    if args.shopping_list:
        generate_shopping_list()
        return

    console = Console()
    dashboard = TerminalDashboard(console)
    tracker = TemporalTracker()
    classifier = SensorFusionClassifier()
    beeper = ProximityBeeper(enabled=not args.mute)

    # Instantiate collectors
    bt_collector = BluetoothCollector()
    wifi_collector = WiFiCollector()
    sdr_collector = SDRCollector()
    gps_collector = GPSCollector()
    mock_collector = MockCollector(scenario=args.scenario) if args.mock else None

    # Probe and start collectors
    if args.mock:
        mock_collector.start()
        active_collectors = [mock_collector]
    else:
        collectors = [bt_collector, wifi_collector, sdr_collector, gps_collector]
        active_collectors = []
        for col in collectors:
            health = col.probe_hardware()
            if health.status == ModuleStatus.ACTIVE:
                if col.start():
                    active_collectors.append(col)

    if args.oneshot:
        # Perform single snapshot
        health_list = [
            bt_collector.probe_hardware(),
            wifi_collector.probe_hardware(),
            sdr_collector.probe_hardware(),
            gps_collector.probe_hardware(),
        ]
        if args.mock:
            health_list.append(mock_collector.probe_hardware())

        observations: List[RawObservation] = []
        for col in active_collectors:
            observations.extend(col.poll())

        geo_fix = mock_collector.get_fix() if args.mock else gps_collector.get_fix()
        tracker.update(observations, geo_fix.speed_kmh)
        entities = tracker.get_active_entities()
        bins = mock_collector.get_spectrum_bins() if args.mock else sdr_collector.get_spectrum_bins()
        result = classifier.evaluate(entities, bins, geo_fix)

        renderable = dashboard.render_layout(
            geo_fix=geo_fix,
            is_mock=args.mock,
            scenario_name=args.scenario if args.mock else "",
            health_list=health_list,
            result=result,
            entities=entities,
            bins=bins,
            audio_enabled=beeper.enabled
        )
        console.print(renderable)
        return

    # Start audio proximity thread
    beeper.start()

    # Continuous Live Terminal Loop
    try:
        with Live(console=console, screen=True, refresh_per_second=int(1.0 / max(0.2, args.interval))) as live:
            while True:
                health_list = []
                if args.mock:
                    health_list.append(mock_collector.health)
                else:
                    health_list = [
                        bt_collector.health,
                        wifi_collector.health,
                        sdr_collector.health,
                        gps_collector.health,
                    ]

                observations: List[RawObservation] = []
                for col in active_collectors:
                    observations.extend(col.poll())

                geo_fix = mock_collector.get_fix() if args.mock else gps_collector.get_fix()
                tracker.update(observations, geo_fix.speed_kmh)
                entities = tracker.get_active_entities()
                bins = mock_collector.get_spectrum_bins() if args.mock else sdr_collector.get_spectrum_bins()
                result = classifier.evaluate(entities, bins, geo_fix)

                # Determine highest proximity RSSI among active targets
                peak_rssi = max((e.current_rssi for e in entities), default=-100.0)
                # Feed proximity beeper
                beeper.update_state(result.probability_pct, peak_rssi)

                if args.log:
                    log_telemetry(args.log, result, geo_fix, len(observations))

                renderable = dashboard.render_layout(
                    geo_fix=geo_fix,
                    is_mock=args.mock,
                    scenario_name=args.scenario if args.mock else "",
                    health_list=health_list,
                    result=result,
                    entities=entities,
                    bins=bins,
                    audio_enabled=beeper.enabled
                )
                live.update(renderable)
                time.sleep(args.interval)

    except KeyboardInterrupt:
        pass
    finally:
        beeper.stop()
        for col in active_collectors:
            col.stop()
        console.print("[dim]Scanner shutdown complete. Hardware handles released.[/dim]")


if __name__ == "__main__":
    main()
