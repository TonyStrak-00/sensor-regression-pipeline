"""
test_sensor_processor.py
Unit tests for the SensorProcessor module.
These run on every commit — fast, isolated, no hardware needed.
"""

import pytest
import time
import struct
from sensor_pipeline.sensor_processor import (
    SensorProcessor,
    SensorReading,
    SensorConfig,
    SensorStatus,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def default_configs():
    return [
        SensorConfig(
            sensor_id=1, name="Temperature", min_value=-40.0, max_value=125.0,
            warning_threshold=80.0, fault_threshold=100.0,
        ),
        SensorConfig(
            sensor_id=2, name="Pressure", min_value=0.0, max_value=1000.0,
            warning_threshold=800.0, fault_threshold=950.0,
        ),
        SensorConfig(
            sensor_id=3, name="Voltage", min_value=0.0, max_value=60.0,
            warning_threshold=50.0, fault_threshold=55.0,
        ),
    ]


@pytest.fixture
def processor(default_configs):
    return SensorProcessor(default_configs)


def make_reading(sensor_id=1, value=25.0, status=SensorStatus.OK):
    return SensorReading(
        sensor_id=sensor_id,
        timestamp=time.time(),
        value=value,
        status=status,
    )


# ─── Test: Basic Processing ──────────────────────────────────────────────────

class TestBasicProcessing:
    def test_process_normal_reading(self, processor):
        reading = make_reading(sensor_id=1, value=25.0)
        result = processor.process_reading(reading)
        assert result.status == SensorStatus.OK

    def test_process_warning_reading(self, processor):
        reading = make_reading(sensor_id=1, value=85.0)
        result = processor.process_reading(reading)
        assert result.status == SensorStatus.WARNING

    def test_process_fault_reading(self, processor):
        reading = make_reading(sensor_id=1, value=105.0)
        result = processor.process_reading(reading)
        assert result.status == SensorStatus.FAULT

    def test_out_of_range_low(self, processor):
        reading = make_reading(sensor_id=1, value=-50.0)
        result = processor.process_reading(reading)
        assert result.status == SensorStatus.FAULT

    def test_out_of_range_high(self, processor):
        reading = make_reading(sensor_id=1, value=130.0)
        result = processor.process_reading(reading)
        assert result.status == SensorStatus.FAULT

    def test_unknown_sensor_raises(self, processor):
        reading = make_reading(sensor_id=99, value=10.0)
        with pytest.raises(ValueError, match="Unknown sensor ID"):
            processor.process_reading(reading)


# ─── Test: Batch Processing ──────────────────────────────────────────────────

class TestBatchProcessing:
    def test_batch_all_ok(self, processor):
        readings = [make_reading(sensor_id=1, value=v) for v in [20.0, 30.0, 40.0]]
        results = processor.process_batch(readings)
        assert all(r.status == SensorStatus.OK for r in results)

    def test_batch_mixed_status(self, processor):
        readings = [
            make_reading(sensor_id=1, value=25.0),   # OK
            make_reading(sensor_id=1, value=85.0),   # WARNING
            make_reading(sensor_id=1, value=105.0),  # FAULT
        ]
        results = processor.process_batch(readings)
        assert results[0].status == SensorStatus.OK
        assert results[1].status == SensorStatus.WARNING
        assert results[2].status == SensorStatus.FAULT

    def test_batch_empty(self, processor):
        results = processor.process_batch([])
        assert results == []


# ─── Test: Running Average ───────────────────────────────────────────────────

class TestRunningAverage:
    def test_single_reading(self, processor):
        processor.process_reading(make_reading(sensor_id=1, value=50.0))
        assert processor.get_running_average(1) == 50.0

    def test_multiple_readings(self, processor):
        for v in [10.0, 20.0, 30.0]:
            processor.process_reading(make_reading(sensor_id=1, value=v))
        avg = processor.get_running_average(1)
        assert abs(avg - 20.0) < 0.001

    def test_no_readings(self, processor):
        assert processor.get_running_average(1) is None


# ─── Test: Fault Logging ────────────────────────────────────────────────────

class TestFaultLogging:
    def test_fault_logged(self, processor):
        processor.process_reading(make_reading(sensor_id=1, value=105.0))
        faults = processor.get_fault_log()
        assert len(faults) == 1
        assert faults[0]["reason"] == "FAULT_THRESHOLD"

    def test_out_of_range_logged(self, processor):
        processor.process_reading(make_reading(sensor_id=1, value=130.0))
        faults = processor.get_fault_log()
        assert len(faults) == 1
        assert faults[0]["reason"] == "OUT_OF_RANGE"

    def test_no_fault_for_ok(self, processor):
        processor.process_reading(make_reading(sensor_id=1, value=25.0))
        assert len(processor.get_fault_log()) == 0

    def test_no_fault_for_warning(self, processor):
        processor.process_reading(make_reading(sensor_id=1, value=85.0))
        assert len(processor.get_fault_log()) == 0


# ─── Test: Serialization ────────────────────────────────────────────────────

class TestSerialization:
    def test_round_trip(self):
        original = make_reading(sensor_id=2, value=123.456)
        data = original.to_bytes()
        restored = SensorReading.from_bytes(data)
        assert restored.sensor_id == original.sensor_id
        assert abs(restored.value - original.value) < 0.001

    def test_insufficient_data(self):
        with pytest.raises(ValueError, match="Insufficient data"):
            SensorReading.from_bytes(b"\x00" * 5)


# ─── Test: Reset ─────────────────────────────────────────────────────────────

class TestReset:
    def test_reset_clears_readings(self, processor):
        processor.process_reading(make_reading(sensor_id=1, value=25.0))
        processor.reset()
        assert processor.get_running_average(1) is None

    def test_reset_clears_faults(self, processor):
        processor.process_reading(make_reading(sensor_id=1, value=105.0))
        processor.reset()
        assert len(processor.get_fault_log()) == 0

    def test_reset_clears_status_filter(self, processor):
        processor.process_reading(make_reading(sensor_id=1, value=105.0))
        processor.reset()
        assert len(processor.get_readings_by_status(SensorStatus.FAULT)) == 0
