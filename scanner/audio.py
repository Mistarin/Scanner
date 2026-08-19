"""Proximity Audio Beeper: Emits acoustic pulses scaling with target signal strength & risk."""

import io
import math
import os
import shutil
import struct
import subprocess
import sys
import threading
import time
import wave
from typing import Optional


class ProximityBeeper:
    def __init__(self, enabled: bool = True, min_prob_pct: float = 35.0):
        self.enabled = enabled
        self.min_prob_pct = min_prob_pct
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # State shared with engine
        self._target_rssi: float = -100.0
        self._probability_pct: float = 0.0
        self._is_active: bool = False

        # Generate a short 60ms 950Hz beep WAV in memory for instant low-latency playback
        self._wav_bytes = self._generate_beep_wav(freq_hz=950, duration_sec=0.055, volume=0.35)
        self._wav_path = "/tmp/scanner_beep.wav"
        try:
            with open(self._wav_path, "wb") as f:
                f.write(self._wav_bytes)
        except Exception:
            self._wav_path = None

        # Detect best audio backend on Linux
        self._backend = self._detect_backend()

    def _detect_backend(self) -> str:
        if shutil.which("paplay") and self._wav_path and os.path.exists(self._wav_path):
            return "paplay"
        elif shutil.which("pw-play") and self._wav_path and os.path.exists(self._wav_path):
            return "pw-play"
        elif shutil.which("aplay") and self._wav_path and os.path.exists(self._wav_path):
            return "aplay"
        else:
            return "terminal_bell"

    def _generate_beep_wav(self, freq_hz: int, duration_sec: float, volume: float) -> bytes:
        sample_rate = 22050
        num_samples = int(sample_rate * duration_sec)
        buf = io.BytesIO()

        with wave.open(buf, "wb") as w:
            w.setnchannels(1)  # Mono
            w.setsampwidth(2)  # 16-bit
            w.setframerate(sample_rate)

            # Create sine wave with soft decay envelope to avoid speaker click
            frames = bytearray()
            for i in range(num_samples):
                t = float(i) / sample_rate
                # Exponential decay envelope
                envelope = math.exp(-3.5 * (i / num_samples))
                val = math.sin(2.0 * math.pi * freq_hz * t) * envelope * volume
                sample = int(max(-32767, min(32767, val * 32767)))
                frames.extend(struct.pack("<h", sample))

            w.writeframes(frames)

        return buf.getvalue()

    def update_state(self, probability_pct: float, peak_rssi: float) -> None:
        """Called by main loop to update proximity parameters."""
        with self._lock:
            self._probability_pct = probability_pct
            self._target_rssi = peak_rssi
            self._is_active = (probability_pct >= self.min_prob_pct and peak_rssi > -85.0)

    def _play_single_beep(self):
        try:
            if self._backend == "paplay" and self._wav_path:
                subprocess.Popen(
                    ["paplay", self._wav_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            elif self._backend == "pw-play" and self._wav_path:
                subprocess.Popen(
                    ["pw-play", self._wav_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            elif self._backend == "aplay" and self._wav_path:
                subprocess.Popen(
                    ["aplay", "-q", self._wav_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                # Terminal bell fallback
                sys.stdout.write("\a")
                sys.stdout.flush()
        except Exception:
            pass

    def start(self) -> None:
        if not self.enabled or self.is_running:
            return
        self.is_running = True
        self._thread = threading.Thread(target=self._beeper_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.is_running = False
        if self._thread:
            self._thread.join(timeout=0.5)
            self._thread = None

    def _beeper_loop(self) -> None:
        while self.is_running:
            with self._lock:
                active = self._is_active
                rssi = self._target_rssi
                prob = self._probability_pct

            if not active:
                time.sleep(0.15)
                continue

            # Calculate interval based on proximity:
            # -85 dBm (far) -> 1.6s interval
            # -65 dBm (medium) -> 0.7s interval
            # -50 dBm (close) -> 0.3s interval
            # -38 dBm (very close) -> 0.10s rapid Geiger pulse
            clamped_rssi = max(-85.0, min(-35.0, rssi))
            # Normalized 0.0 (far) to 1.0 (very close)
            closeness = (clamped_rssi - (-85.0)) / ((-35.0) - (-85.0))

            # Exponential speedup
            interval = 1.6 * math.pow(0.08, closeness)
            # Probability factor: higher confidence slightly tightens interval
            confidence_factor = max(0.6, 1.2 - (prob / 100.0))
            final_interval = max(0.08, min(2.0, interval * confidence_factor))

            self._play_single_beep()
            time.sleep(final_interval)
