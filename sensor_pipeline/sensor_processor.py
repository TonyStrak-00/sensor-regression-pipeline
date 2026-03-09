"""
sensor_processor.py
Simulates embedded sensor data acquisition and processing.
Think of this as a Python model of what your firmware does on ARM hardware.
"""

import struct
import time
from dataclasses import dataclass, field
from typing import List, Optional
from enum import IntEnum


class SensorStatus(IntEnum):
    OK = 0
    WARNING = 1
    FAULT = 2
    OFFLINE = 3


@dataclass
class SensorReading:
    sensor_id: int
    timestamp: float
    value: float
    status: SensorStatus = SensorStatus.OK
    raw_bytes: bytes = b""

    def to_bytes(self) -> bytes:
        """Pack sensor reading into binary format (simulates firmware wire format)."""
        return struct.pack(
            "<BdfB",
            self.sensor_id,
            self.timestamp,
            self.value,
            int(self.status),
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "SensorReading":
        """Unpack binary data into a SensorReading (simulates firmware deserialization)."""
        if len(data) < 18:
            raise ValueError(f"Insufficient data: expected 18 bytes, got {len(data)}")
        sensor_id, timestamp, value, status = struct.unpack("<BdfB", data[:18])
        return cls(
            sensor_id=sensor_id,
            timestamp=timestamp,
            value=value,
            status=SensorStatus(status),
            raw_bytes=data,
        )


@dataclass
class SensorConfig:
    sensor_id: int
    name: str
    min_value: float
    max_value: float
    warning_threshold: float
    fault_threshold: float
    sample_rate_hz: float = 10.0


class SensorProcessor:
    """
    Processes incoming sensor data, applies thresholds, and detects faults.
    Models the kind of processing you'd do in an embedded RTOS task.
    """

    def __init__(self, configs: List[SensorConfig]):
        self._configs = {cfg.sensor_id: cfg for cfg in configs}
        self._readings: List[SensorReading] = []
        self._fault_log: List[dict] = []
        self._running_avg: dict = {}

    @property
    def configs(self) -> dict:
        return self._configs

    def process_reading(self, reading: SensorReading) -> SensorReading:
        """Process a single sensor reading: validate, threshold check, update status."""
        config = self._configs.get(reading.sensor_id)
        if config is None:
            raise ValueError(f"Unknown sensor ID: {reading.sensor_id}")

        # Range validation
        if reading.value < config.min_value or reading.value > config.max_value:
            reading.status = SensorStatus.FAULT
            self._log_fault(reading, "OUT_OF_RANGE")
        elif abs(reading.value) >= config.fault_threshold:
            reading.status = SensorStatus.FAULT
            self._log_fault(reading, "FAULT_THRESHOLD")
        elif abs(reading.value) >= config.warning_threshold:
            reading.status = SensorStatus.WARNING

        # Update running average
        self._update_running_avg(reading)
        self._readings.append(reading)
        return reading

    def process_batch(self, readings: List[SensorReading]) -> List[SensorReading]:
        """Process a batch of readings — simulates processing a DMA buffer."""
        return [self.process_reading(r) for r in readings]

    def get_running_average(self, sensor_id: int) -> Optional[float]:
        """Get the running average for a sensor."""
        avg_data = self._running_avg.get(sensor_id)
        if avg_data is None or avg_data["count"] == 0:
            return None
        return avg_data["sum"] / avg_data["count"]

    def get_fault_log(self) -> List[dict]:
        return list(self._fault_log)

    def get_readings_by_status(self, status: SensorStatus) -> List[SensorReading]:
        return [r for r in self._readings if r.status == status]

    def reset(self):
        """Reset processor state — simulates a firmware watchdog reset."""
        self._readings.clear()
        self._fault_log.clear()
        self._running_avg.clear()

    def _update_running_avg(self, reading: SensorReading):
        sid = reading.sensor_id
        if sid not in self._running_avg:
            self._running_avg[sid] = {"sum": 0.0, "count": 0}
        self._running_avg[sid]["sum"] += reading.value
        self._running_avg[sid]["count"] += 1

    def _log_fault(self, reading: SensorReading, reason: str):
        self._fault_log.append({
            "sensor_id": reading.sensor_id,
            "timestamp": reading.timestamp,
            "value": reading.value,
            "reason": reason,
        })
