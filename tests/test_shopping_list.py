"""Unit tests for Hardware Auditor and Shopping List Generator."""

import os
import unittest
from scanner.shopping_list import audit_hardware, generate_shopping_list


class TestShoppingList(unittest.TestCase):
    def test_audit_hardware_keys(self):
        audit = audit_hardware()
        self.assertIsInstance(audit, dict)
        self.assertIn("bt_front", audit)
        self.assertIn("wifi_monitor", audit)
        self.assertIn("sdr_primary", audit)
        self.assertIn("gps_receiver", audit)

    def test_generate_shopping_list_output(self):
        test_md = "/tmp/test_shopping_list.md"
        content = generate_shopping_list(save_markdown=True, output_path=test_md)
        
        self.assertTrue(os.path.exists(test_md))
        self.assertIn("RTL-SDR", content)
        self.assertIn("Bluetooth", content)
        self.assertIn("Approx. Price", content)
        
        # Cleanup
        if os.path.exists(test_md):
            os.remove(test_md)


if __name__ == "__main__":
    unittest.main()
