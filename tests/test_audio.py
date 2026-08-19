"""Unit tests for Proximity Audio Beeper."""

import unittest
from scanner.audio import ProximityBeeper


class TestAudioBeeper(unittest.TestCase):
    def test_audio_beeper_initialization(self):
        beeper = ProximityBeeper(enabled=True, min_prob_pct=35.0)
        self.assertTrue(beeper.enabled)
        self.assertIn(beeper._backend, ("paplay", "pw-play", "aplay", "terminal_bell"))

    def test_audio_beeper_state_activation(self):
        beeper = ProximityBeeper(enabled=True, min_prob_pct=35.0)
        
        # Below threshold -> inactive
        beeper.update_state(probability_pct=20.0, peak_rssi=-50.0)
        self.assertFalse(beeper._is_active)

        # Above threshold + strong RSSI -> active
        beeper.update_state(probability_pct=75.0, peak_rssi=-48.0)
        self.assertTrue(beeper._is_active)

    def test_audio_beeper_lifecycle(self):
        beeper = ProximityBeeper(enabled=True)
        beeper.start()
        self.assertTrue(beeper.is_running)
        beeper.stop()
        self.assertFalse(beeper.is_running)


if __name__ == "__main__":
    unittest.main()
