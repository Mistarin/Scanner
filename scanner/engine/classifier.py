"""Multi-factor Statistical Classifier & Sensor Fusion Engine."""

import math
from datetime import datetime
from typing import List
from scanner.models import (
    ClassificationResult,
    FeatureScore,
    GeoFix,
    SensorType,
    SignalTrend,
    SpectrumBin,
    TrackedEntity,
)


class SensorFusionClassifier:
    KNOWN_SIGNATURES = [
        ("teltonika", 4.5, "Teltonika Networks In-Vehicle Gateway (RUTX/RUT9)"),
        ("advantech", 4.5, "Advantech Conel SmartFlex/ICR In-Vehicle Router"),
        ("sepura", 5.0, "Sepura TETRA/PEGAS Mobile Terminal (SC20/STP)"),
        ("motorola", 4.5, "Motorola Solutions TETRA Terminal (MTP/MTM/Dimetra)"),
        ("matra", 4.5, "Matra / TETRAPOL Emergency Telemetry"),
        ("skoda", 3.0, "Škoda Auto In-Car Infotainment / SmartLink"),
        ("kapsch", 4.0, "Kapsch / European DSRC ITS Telemetry"),
        ("sierra wireless", 4.0, "Sierra Wireless AirLink Telematics Router"),
        ("cradlepoint", 4.0, "Cradlepoint In-Vehicle Router"),
    ]

    def evaluate(
        self,
        entities: List[TrackedEntity],
        spectrum_bins: List[SpectrumBin],
        geo_fix: GeoFix
    ) -> ClassificationResult:
        features: List[FeatureScore] = []

        ble_entities = [e for e in entities if e.sensor == SensorType.BLUETOOTH]
        wifi_entities = [e for e in entities if e.sensor == SensorType.WIFI]
        rf_entities = [e for e in entities if e.sensor == SensorType.SDR_RF]

        # 1. BLE Device Count / Cluster Density
        ble_count = len(ble_entities)
        if ble_count >= 12:
            features.append(FeatureScore(
                name="BLE Cluster Density",
                category="RF/BLE",
                raw_value=f"{ble_count} devices",
                weight=1.0,
                points=3.0,
                description="Dense Bluetooth cluster (12+ active emitters in close proximity)"
            ))
        elif ble_count >= 6:
            features.append(FeatureScore(
                name="BLE Cluster Density",
                category="RF/BLE",
                raw_value=f"{ble_count} devices",
                weight=1.0,
                points=1.5,
                description="Moderate Bluetooth density (6–11 active emitters)"
            ))

        # 2. Known Equipment & Vendor Signatures
        known_hits = []
        for e in entities:
            combined_label = f"{e.name_or_ssid} {e.vendor}".lower()
            for pattern, pts, desc in self.KNOWN_SIGNATURES:
                if pattern in combined_label:
                    known_hits.append((e.name_or_ssid or e.identifier, pts, desc))

        if known_hits:
            best_hit = max(known_hits, key=lambda x: x[1])
            features.append(FeatureScore(
                name="Hardware Signature",
                category="Identifier",
                raw_value=best_hit[0],
                weight=1.0,
                points=best_hit[1],
                description=f"Identified known equipment pattern: {best_hit[2]}"
            ))

        # 3. Co-moving Transmitter Gradient (Pacing with vehicle)
        co_moving = [e for e in entities if e.is_co_traveling]
        if co_moving and geo_fix.speed_kmh > 25.0:
            features.append(FeatureScore(
                name="Co-traveling RF Gradient",
                category="Spatial Dynamics",
                raw_value=f"{len(co_moving)} emitters pacing",
                weight=1.0,
                points=4.0,
                description=f"Stable RSSI (σ < 2.5dB) across multiple emitters while moving at {geo_fix.speed_kmh:.0f} km/h"
            ))

        # 4. Approaching Signal Gradient
        approaching = [e for e in entities if e.trend == SignalTrend.APPROACHING]
        if approaching:
            max_slope = max(e.rssi_slope for e in approaching)
            features.append(FeatureScore(
                name="Approaching Transmitter",
                category="Spatial Dynamics",
                raw_value=f"+{max_slope:.1f} dB/s slope",
                weight=1.0,
                points=2.0,
                description=f"{len(approaching)} source(s) exhibiting rapid signal increase toward vehicle"
            ))

        # 5. SDR RF Target Band Carrier Spikes
        carrier_bursts = [b for b in spectrum_bins if b.is_carrier_burst]
        if carrier_bursts:
            highest_snr = max(b.snr_db for b in carrier_bursts)
            burst_freq = carrier_bursts[0].center_freq_mhz
            features.append(FeatureScore(
                name="RF Carrier Peak (TETRA/UHF)",
                category="Spectrum",
                raw_value=f"{burst_freq:.3f} MHz (+{highest_snr:.1f}dB)",
                weight=1.0,
                points=4.0,
                description=f"High-energy burst detected above baseline noise in target surveillance band"
            ))

        # 6. Mobile In-Vehicle Hotspot
        hotspots = [e for e in wifi_entities if e.is_mobile_hotspot]
        if hotspots and (geo_fix.speed_kmh > 20.0 or co_moving):
            features.append(FeatureScore(
                name="In-Vehicle Mobile Hotspot",
                category="Wi-Fi",
                raw_value=f"{len(hotspots)} hotspot(s)",
                weight=1.0,
                points=1.5,
                description="Cellular vehicular Wi-Fi router / mobile hotspot detected"
            ))

        # 7. Contextual Traffic Dampener (Avoid false positives in static gridlock)
        if geo_fix.speed_kmh < 10.0 and ble_count > 10 and not carrier_bursts and not known_hits:
            features.append(FeatureScore(
                name="Commuter Traffic Baseline",
                category="Context",
                raw_value=f"{geo_fix.speed_kmh:.0f} km/h (Gridlock)",
                weight=1.0,
                points=-2.5,
                description="High device density correlated with stationary commuter congestion"
            ))

        # Calculate Total Calibrated Score & Sigmoid Probability
        total_score = sum(f.points for f in features)
        
        # Sigmoid: P = 100 / (1 + exp(-0.5 * (Score - 4.0)))
        # Score 0 -> ~11%
        # Score 4 -> 50%
        # Score 8 -> ~88%
        # Score 12+ -> ~98%
        raw_prob = 100.0 / (1.0 + math.exp(-0.5 * (total_score - 4.0)))
        prob_pct = round(max(3.0, min(98.0, raw_prob)), 1)

        if prob_pct < 25.0:
            risk_level = "LOW"
            summary = "Ambient RF environment consistent with normal traffic baseline."
        elif prob_pct < 55.0:
            risk_level = "ELEVATED"
            summary = "Slight device concentration or mobile hotspot detected nearby."
        elif prob_pct < 80.0:
            risk_level = "HIGH"
            summary = "High probability of targeted vehicle/telemetry cluster nearby."
        else:
            risk_level = "CRITICAL"
            summary = "Strong multi-sensor correlation: Co-traveling cluster + active RF signature."

        return ClassificationResult(
            probability_pct=prob_pct,
            risk_level=risk_level,
            total_score=round(total_score, 1),
            features=features,
            summary_verdict=summary,
            timestamp=datetime.now()
        )
