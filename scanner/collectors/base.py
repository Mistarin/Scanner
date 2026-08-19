"""Abstract base class for all scanner hardware collectors."""

from abc import ABC, abstractmethod
from typing import List, Optional
from scanner.models import ModuleHealth, ModuleStatus, RawObservation, SensorType


class BaseCollector(ABC):
    def __init__(self, sensor_type: SensorType, display_name: str):
        self.sensor_type = sensor_type
        self.display_name = display_name
        self.health = ModuleHealth(
            sensor=sensor_type,
            status=ModuleStatus.INACTIVE,
            display_name=display_name,
            diagnostic_reason="Not probed yet.",
            hardware_detected=False,
            required_device="Generic",
            activation_hint="Module initialization pending."
        )
        self.is_running = False

    @abstractmethod
    def probe_hardware(self) -> ModuleHealth:
        """Inspect system environment, USB busses, device nodes, and CLI tools.
        Updates self.health and returns it.
        """
        pass

    @abstractmethod
    def start(self) -> bool:
        """Start acquisition if hardware probe was successful.
        Returns True if active, False otherwise.
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """Gracefully release hardware handles, subprocesses, or sockets."""
        pass

    @abstractmethod
    def poll(self) -> List[RawObservation]:
        """Poll latest batch of observations without blocking the UI event loop."""
        pass
