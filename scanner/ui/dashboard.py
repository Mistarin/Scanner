"""Terminal UI Dashboard built with Rich for explanatory, non-slop RF telemetry."""

from datetime import datetime
from typing import Dict, List
from rich.console import Console, Group
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from scanner.models import (
    ClassificationResult,
    GeoFix,
    ModuleHealth,
    ModuleStatus,
    SensorType,
    SignalTrend,
    SpatialBearing,
    SpectrumBin,
    TrackedEntity,
)


class TerminalDashboard:
    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()

    def generate_header(self, geo_fix: GeoFix, is_mock: bool, scenario_name: str = "", audio_enabled: bool = True) -> Panel:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mode_text = f"[bold yellow]MOCK SIMULATION ({scenario_name})[/bold yellow]" if is_mock else "[bold green]LIVE SENSORS[/bold green]"
        audio_badge = "[bold green]🔊 AUDIO[/bold green]" if audio_enabled else "[dim]🔇 MUTED[/dim]"
        
        if geo_fix.has_fix:
            speed_color = "green" if geo_fix.speed_kmh < 50 else ("yellow" if geo_fix.speed_kmh < 90 else "cyan")
            geo_text = f"GPS: [bold {speed_color}]{geo_fix.speed_kmh:.1f} km/h[/bold {speed_color}] | Lat: {geo_fix.latitude:.4f} Lon: {geo_fix.longitude:.4f} | Hdg: {geo_fix.heading_deg:.0f}°"
        else:
            geo_text = "GPS: [dim]No Serial Fix (Speed Estimated)[/dim]"

        header_table = Table.grid(expand=True)
        header_table.add_column(justify="left", ratio=1)
        header_table.add_column(justify="center", ratio=1)
        header_table.add_column(justify="right", ratio=1)

        header_table.add_row(
            f"[bold cyan]📡 PASSIVE RF & TELEMETRY SCANNER[/bold cyan] [dim]v0.1.0[/dim]",
            f"Mode: {mode_text} | {audio_badge}",
            f"{geo_text} | [dim]{now_str}[/dim]"
        )
        return Panel(header_table, style="bright_blue", padding=(0, 1))

    def generate_modules_panel(self, health_list: List[ModuleHealth]) -> Panel:
        table = Table(box=None, expand=True, padding=(0, 1))
        table.add_column("Subsystem", style="bold cyan", width=22)
        table.add_column("Status", width=12)
        table.add_column("Diagnostic Reason / Subsystem State", ratio=2)
        table.add_column("Activation Condition / Actionable Hint", style="yellow", ratio=2)

        for h in health_list:
            if h.status == ModuleStatus.ACTIVE:
                status_badge = "[bold green]● ACTIVE[/bold green]"
                hint = f"[green]{h.activation_hint}[/green]"
            elif h.status == ModuleStatus.STANDBY:
                status_badge = "[bold yellow]▲ STANDBY[/bold yellow]"
                hint = f"[yellow]{h.activation_hint}[/yellow]"
            elif h.status == ModuleStatus.ERROR:
                status_badge = "[bold red]✖ ERROR[/bold red]"
                hint = f"[red]{h.activation_hint}[/red]"
            else:
                status_badge = "[dim]○ INACTIVE[/dim]"
                hint = f"[dim]{h.activation_hint}[/dim]"

            table.add_row(
                h.display_name,
                status_badge,
                h.diagnostic_reason,
                hint
            )

        return Panel(table, title="[bold]Hardware Subsystem Matrix[/bold]", border_style="blue", padding=(0, 1))

    def generate_classification_panel(self, result: ClassificationResult) -> Panel:
        # Construct probability bar (24 blocks wide)
        prob = result.probability_pct
        filled = int(round((prob / 100.0) * 24))
        empty = 24 - filled

        if result.risk_level == "CRITICAL":
            bar_color = "red"
            badge = "[bold white on red] CRITICAL [/bold white on red]"
        elif result.risk_level == "HIGH":
            bar_color = "orange3"
            badge = "[bold white on dark_orange] HIGH [/bold white on dark_orange]"
        elif result.risk_level == "ELEVATED":
            bar_color = "yellow"
            badge = "[bold black on yellow] ELEVATED [/bold black on yellow]"
        else:
            bar_color = "green"
            badge = "[bold white on green] LOW [/bold white on green]"

        prob_bar = f"[{bar_color}]{'█' * filled}[/{bar_color}][dim]{'░' * empty}[/dim]"

        # Feature weight ledger table
        feature_table = Table(box=None, expand=True, padding=(0, 1))
        feature_table.add_column("Feature / Factor", style="bold", width=26)
        feature_table.add_column("Category", style="dim", width=16)
        feature_table.add_column("Observed Value", width=22)
        feature_table.add_column("Points", justify="right", width=10)
        feature_table.add_column("Mathematical / Physical Rationale", ratio=1)

        if not result.features:
            feature_table.add_row(
                "[dim]Baseline Environment[/dim]",
                "[dim]Ambient[/dim]",
                "[dim]Normal traffic[/dim]",
                "[dim]0.0[/dim]",
                "[dim]No suspicious signal concentrations, carrier spikes, or pacing emitters detected.[/dim]"
            )
        else:
            for f in result.features:
                pts_color = "green" if f.points > 0 else "cyan"
                pts_sign = f"+{f.points:.1f}" if f.points > 0 else f"{f.points:.1f}"
                feature_table.add_row(
                    f.name,
                    f.category,
                    f"[bold]{f.raw_value}[/bold]",
                    f"[{pts_color}]{pts_sign}[/{pts_color}]",
                    f.description
                )

        summary_text = Text()
        summary_text.append(f"Target Probability: ", style="bold")
        summary_text.append(f"{prob_bar} ")
        summary_text.append(f"{prob:.1f}% ", style=f"bold {bar_color}")
        summary_text.append(f"({badge})  |  ", style="bold")
        summary_text.append(f"Calibrated Score: {result.total_score:+.1f}  |  ", style="dim")
        summary_text.append(result.summary_verdict, style="italic")

        group = Group(
            summary_text,
            Text(""),
            feature_table
        )
        return Panel(group, title="[bold]Sensor-Fusion Classifier & Scoring Matrix[/bold]", border_style=bar_color, padding=(0, 1))

    def generate_targets_panel(self, entities: List[TrackedEntity]) -> Panel:
        table = Table(box=None, expand=True, padding=(0, 1))
        table.add_column("Type", width=8)
        table.add_column("Identifier / MAC", style="bold", width=18)
        table.add_column("Name / SSID", width=22)
        table.add_column("Vendor / Class", width=20)
        table.add_column("RSSI", justify="right", width=9)
        table.add_column("Bearing (ΔF/R)", width=16)
        table.add_column("Signal Trend (dRSSI/dt)", width=24)
        table.add_column("Hits", justify="right", width=5)

        if not entities:
            table.add_row("[dim]--[/dim]", "[dim]No active transmitters[/dim]", "", "", "", "", "", "")
        else:
            for e in entities[:10]:
                # RSSI color
                if e.current_rssi > -55:
                    rssi_styled = f"[bold red]{e.current_rssi:.0f} dBm[/bold red]"
                elif e.current_rssi > -70:
                    rssi_styled = f"[bold yellow]{e.current_rssi:.0f} dBm[/bold yellow]"
                else:
                    rssi_styled = f"[dim]{e.current_rssi:.0f} dBm[/dim]"

                # Bearing display (Front vs Rear delta)
                if e.bearing == SpatialBearing.AHEAD:
                    bearing_str = f"[bold green]▲ AHEAD[/bold green] [dim](+{e.delta_rssi:+.0f}dB)[/dim]"
                elif e.bearing == SpatialBearing.BEHIND:
                    bearing_str = f"[bold orange3]▼ BEHIND[/bold orange3] [dim]({e.delta_rssi:+.0f}dB)[/dim]"
                elif e.bearing == SpatialBearing.ALONGSIDE:
                    bearing_str = f"[bold cyan]◄► ALONG[/bold cyan] [dim](~0dB)[/dim]"
                else:
                    bearing_str = "[dim]○ OMNI[/dim]"

                # Trend display
                if e.trend == SignalTrend.APPROACHING:
                    trend_str = f"[bold red]▲ APPROACH[/bold red] [dim](+{e.rssi_slope:.1f} dB/s)[/dim]"
                elif e.trend == SignalTrend.CO_TRAVELING:
                    trend_str = f"[bold orange3]► PACING[/bold orange3] [dim](σ={e.rssi_variance:.1f}dB)[/dim]"
                elif e.trend == SignalTrend.RECEDING:
                    trend_str = f"[bold green]▼ RECEDE[/bold green] [dim]({e.rssi_slope:.1f} dB/s)[/dim]"
                elif e.trend == SignalTrend.STATIONARY:
                    trend_str = "[dim]● STATIC[/dim]"
                else:
                    trend_str = "[dim]~ TRANS[/dim]"

                sensor_badge = {
                    SensorType.BLUETOOTH: "[cyan]BLE[/cyan]",
                    SensorType.WIFI: "[magenta]Wi-Fi[/magenta]",
                    SensorType.SDR_RF: "[red]RF SDR[/red]",
                    SensorType.MOCK: "[yellow]SIM[/yellow]",
                }.get(e.sensor, "[white]UNK[/white]")

                table.add_row(
                    sensor_badge,
                    e.identifier,
                    e.name_or_ssid or "[dim]Anonymous[/dim]",
                    e.vendor or "[dim]Unknown[/dim]",
                    rssi_styled,
                    bearing_str,
                    trend_str,
                    str(e.hit_count)
                )

        return Panel(table, title="[bold]Active Tracked Emitters (Bidirectional Spatial Tracking)[/bold]", border_style="cyan", padding=(0, 1))

    def generate_spectrum_panel(self, bins: List[SpectrumBin]) -> Panel:
        table = Table(box=None, expand=True, padding=(0, 1))
        table.add_column("Center Freq", style="bold", width=14)
        table.add_column("Band Label", width=18)
        table.add_column("Power (dBm)", justify="right", width=12)
        table.add_column("Noise Floor", justify="right", width=12)
        table.add_column("SNR", justify="right", width=10)
        table.add_column("Spectral Power Level vs Ambient Noise", ratio=1)

        if not bins:
            table.add_row("[dim]--[/dim]", "[dim]RTL-SDR Inactive[/dim]", "", "", "", "[dim]Plug in RTL-SDR dongle to view live spectrum power grid.[/dim]")
        else:
            for b in bins[:8]:
                # Draw small visual bar for SNR (max 30dB scale)
                snr_bars = max(0, min(25, int(b.snr_db)))
                if b.is_carrier_burst:
                    power_bar = f"[bold red]{'█' * snr_bars}[/bold red] [bold red]BURST DETECTED[/bold red]"
                    freq_style = "bold red"
                elif b.snr_db > 6.0:
                    power_bar = f"[yellow]{'█' * snr_bars}[/yellow]"
                    freq_style = "yellow"
                else:
                    power_bar = f"[dim]{'█' * max(1, snr_bars)}[/dim]"
                    freq_style = "dim"

                table.add_row(
                    f"[{freq_style}]{b.center_freq_mhz:.3f} MHz[/{freq_style}]",
                    b.band_label,
                    f"{b.power_dbm:.1f} dBm",
                    f"{b.noise_floor_dbm:.1f} dBm",
                    f"+{b.snr_db:.1f} dB",
                    power_bar
                )

        return Panel(table, title="[bold]RF Spectrum Sweep (Emergency / TETRA / ISM Channels)[/bold]", border_style="magenta", padding=(0, 1))

    def render_layout(
        self,
        geo_fix: GeoFix,
        is_mock: bool,
        scenario_name: str,
        health_list: List[ModuleHealth],
        result: ClassificationResult,
        entities: List[TrackedEntity],
        bins: List[SpectrumBin],
        audio_enabled: bool = True
    ) -> Group:
        return Group(
            self.generate_header(geo_fix, is_mock, scenario_name, audio_enabled),
            self.generate_modules_panel(health_list),
            self.generate_classification_panel(result),
            self.generate_targets_panel(entities),
            self.generate_spectrum_panel(bins),
        )
