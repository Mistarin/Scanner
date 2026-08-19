"""Hardware Auditor & Dynamic Shopping List Generator."""

import glob
import os
import shutil
from typing import Dict, List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from scanner.collectors.bluetooth_collector import BluetoothCollector
from scanner.collectors.gps_collector import GPSCollector
from scanner.collectors.sdr_collector import SDRCollector
from scanner.collectors.wifi_collector import WiFiCollector
from scanner.models import ModuleStatus


# Catalog of potential hardware upgrades with search terms, pricing, and URL placeholders
HARDWARE_CATALOG = [
    {
        "key": "sdr_primary",
        "name": "RTL-SDR Receiver #1 (Primary Spectrum)",
        "category": "SDR / RF",
        "search_term": "RTL-SDR Blog V4 official SMA",
        "approx_czk": "750–900 Kč",
        "approx_eur": "€30–38",
        "unlocks": "Enables 380–395 MHz European TETRA/PEGAS, PMR446, and 433/868 MHz spectrum sweeps.",
        "url": "https://www.aliexpress.com/item/...",
    },
    {
        "key": "sdr_secondary",
        "name": "RTL-SDR Receiver #2 (Dual Band / Directional)",
        "category": "SDR / RF",
        "search_term": "RTL-SDR Blog V4 official SMA",
        "approx_czk": "750–900 Kč",
        "approx_eur": "€30–38",
        "unlocks": "Simultaneous monitoring of two distinct spectrum slices or dual-antenna RF bearing.",
        "url": "https://www.aliexpress.com/item/...",
    },
    {
        "key": "bt_front",
        "name": "USB Bluetooth 5.0 Dongle (Front Antenna)",
        "category": "Bluetooth / BLE",
        "search_term": "CSR8510 USB Bluetooth 5.0 adapter",
        "approx_czk": "150–250 Kč",
        "approx_eur": "€6–10",
        "unlocks": "Front-facing BLE receiver for bidirectional delta RSSI (Ahead vs Behind).",
        "url": "https://www.aliexpress.com/item/...",
    },
    {
        "key": "bt_rear",
        "name": "USB Bluetooth 5.0 Dongle (Rear Antenna)",
        "category": "Bluetooth / BLE",
        "search_term": "CSR8510 USB Bluetooth 5.0 adapter",
        "approx_czk": "150–250 Kč",
        "approx_eur": "€6–10",
        "unlocks": "Rear-facing BLE receiver to detect trailing vehicles approaching from behind.",
        "url": "https://www.aliexpress.com/item/...",
    },
    {
        "key": "wifi_monitor",
        "name": "Monitor-Mode USB Wi-Fi Adapter",
        "category": "Wi-Fi (802.11)",
        "search_term": "MT7612U USB WiFi adapter with external antennas",
        "approx_czk": "350–550 Kč",
        "approx_eur": "€14–22",
        "unlocks": "Zero-latency passive 802.11 beacon & probe frame sniffing with Radiotap SNR.",
        "url": "https://www.aliexpress.com/item/...",
    },
    {
        "key": "gps_receiver",
        "name": "USB GPS / GLONASS Receiver",
        "category": "GPS / Navigation",
        "search_term": "VK-172 USB GPS GLONASS or u-blox 7 USB",
        "approx_czk": "200–300 Kč",
        "approx_eur": "€8–12",
        "unlocks": "Real-time velocity baseline, heading calculation, and geo-tagged telemetry logging.",
        "url": "https://www.aliexpress.com/item/...",
    },
    {
        "key": "mag_roof_antenna",
        "name": "VHF/UHF Magnetic Roof Antenna (50Ω SMA)",
        "category": "Antenna / RF",
        "search_term": "VHF UHF magnetic mount antenna SMA 50 ohm 136-470MHz",
        "approx_czk": "250–400 Kč",
        "approx_eur": "€10–16",
        "unlocks": "High-efficiency signal reception outside vehicle metal Faraday cage.",
        "url": "https://www.aliexpress.com/item/...",
    },
    {
        "key": "rg316_coax",
        "name": "RG316 50Ω SMA Coax Extension Cables (x2)",
        "category": "RF Accessories",
        "search_term": "RG316 SMA male to SMA female 50 ohm 2m",
        "approx_czk": "100–180 Kč",
        "approx_eur": "€4–7",
        "unlocks": "Routing RF cables through vehicle door seals without pinching.",
        "url": "https://www.aliexpress.com/item/...",
    },
    {
        "key": "buck_converter",
        "name": "12V to 5V 5A Automotive Buck Converter (USB-C)",
        "category": "Power / Car",
        "search_term": "12V to 5V 5A USB-C buck converter step down automotive",
        "approx_czk": "150–250 Kč",
        "approx_eur": "€6–10",
        "unlocks": "Stable, noise-filtered 5V/5A power without vehicle voltage spikes.",
        "url": "https://www.aliexpress.com/item/...",
    },
    {
        "key": "usb_hub",
        "name": "USB 3.0 Powered Hub (4-Port)",
        "category": "USB Infrastructure",
        "search_term": "USB 3.0 powered hub 4-port 12V 5V",
        "approx_czk": "300–500 Kč",
        "approx_eur": "€12–20",
        "unlocks": "Powers multiple SDRs and Wi-Fi dongles without laptop port brownouts.",
        "url": "https://www.aliexpress.com/item/...",
    },
]


def audit_hardware() -> Dict[str, bool]:
    """Inspect local system and return dict of installed component status."""
    status_map = {}

    # 1. Check Bluetooth adapters count
    bt_ifaces = []
    if os.path.exists("/sys/class/bluetooth"):
        bt_ifaces = os.listdir("/sys/class/bluetooth")
    status_map["bt_front"] = len(bt_ifaces) >= 1
    status_map["bt_rear"] = len(bt_ifaces) >= 2

    # 2. Check Wi-Fi interfaces
    wifi_col = WiFiCollector()
    wifi_h = wifi_col.probe_hardware()
    status_map["wifi_monitor"] = (wifi_h.status == ModuleStatus.ACTIVE)

    # 3. Check SDR dongles
    sdr_col = SDRCollector()
    sdr_h = sdr_col.probe_hardware()
    status_map["sdr_primary"] = (sdr_h.status == ModuleStatus.ACTIVE)
    status_map["sdr_secondary"] = False  # Set False until multi-SDR is detected

    # 4. Check GPS
    gps_col = GPSCollector()
    gps_h = gps_col.probe_hardware()
    status_map["gps_receiver"] = (gps_h.status == ModuleStatus.ACTIVE)

    # Accessories default to False unless marked
    status_map["mag_roof_antenna"] = False
    status_map["rg316_coax"] = False
    status_map["buck_converter"] = False
    status_map["usb_hub"] = False

    return status_map


def generate_shopping_list(save_markdown: bool = True, output_path: str = "shopping_list.md") -> str:
    console = Console()
    audit = audit_hardware()

    table = Table(title="[bold cyan]Hardware Audit & Recommended Upgrade Shopping List[/bold cyan]", expand=True)
    table.add_column("Status", width=12)
    table.add_column("Component Name", style="bold", width=28)
    table.add_column("Category", style="dim", width=16)
    table.add_column("Search Term (AliExpress / Local)", width=32)
    table.add_column("Approx. Price", justify="right", width=16)
    table.add_column("Capability Unlocked", ratio=1)

    installed_count = 0
    missing_count = 0
    total_cost_czk_min = 0
    total_cost_czk_max = 0

    md_lines = [
        "# Scanner Hardware Audit & Upgrade Shopping List",
        "",
        "This file is automatically updated based on currently attached physical hardware.",
        "You can customize or paste your exact purchase URLs in the table below.",
        "",
        "| Status | Component | Category | Search Term | Approx. Price | Buy Link | Capability Unlocked |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    ]

    for item in HARDWARE_CATALOG:
        is_installed = audit.get(item["key"], False)
        if is_installed:
            installed_count += 1
            status_str = "[bold green]✔ DETECTED[/bold green]"
            md_status = "✔ DETECTED"
        else:
            missing_count += 1
            status_str = "[bold yellow]🛒 NEEDED[/bold yellow]"
            md_status = "🛒 NEEDED"

        table.add_row(
            status_str,
            item["name"],
            item["category"],
            item["search_term"],
            f"{item['approx_czk']} ({item['approx_eur']})",
            item["unlocks"]
        )

        md_lines.append(
            f"| {md_status} | **{item['name']}** | {item['category']} | `{item['search_term']}` | {item['approx_czk']} ({item['approx_eur']}) | [Link Placeholder]({item['url']}) | {item['unlocks']} |"
        )

    console.print(table)
    summary = f"\n[bold]Audit Summary:[/bold] [green]{installed_count} Installed[/green] | [yellow]{missing_count} Missing / Recommended Upgrades[/yellow]"
    console.print(Panel(summary, style="blue"))

    if save_markdown:
        md_content = "\n".join(md_lines) + "\n"
        with open(output_path, "w") as f:
            f.write(md_content)
        console.print(f"[dim]Saved editable markdown shopping list to: {output_path}[/dim]\n")

    return "\n".join(md_lines)


if __name__ == "__main__":
    generate_shopping_list()
