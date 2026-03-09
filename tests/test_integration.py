"""
test_integration.py
Integration tests — these test multiple modules working together.
Marked as 'slow' so they can be skipped during quick local runs
but always run during nightly regression.
"""

import pytest
import time
import struct
from sensor_pipeline.sensor_processor import (
    SensorProcessor, SensorReading, SensorConfig, SensorStatus,
)
from sensor_pipeline.comm_protocol import (
    ProtocolMessage, MessageType, MessageRouter,
)
from sensor_pipeline.battery_manager import (
    BatteryManager, BatteryPack, CellData, BatteryState, BatteryFault,
)


# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


class TestSensorToProtocol:
    """Test sensor data flowing through the communication protocol."""

    def test_sensor_reading_over_protocol(self):
        """Serialize a sensor reading, send over protocol, deserialize on the other end."""
        # Create and process a sensor reading
        configs = [SensorConfig(
            sensor_id=1, name="Temp", min_value=-40, max_value=125,
            warning_threshold=80, fault_threshold=100,
        )]
        processor = SensorProcessor(configs)
        reading = SensorReading(sensor_id=1, timestamp=time.time(), value=42.5)
        processed = processor.process_reading(reading)

        # Pack the reading into a protocol message
        payload = processed.to_bytes()
        msg = ProtocolMessage(
            msg_type=MessageType.SENSOR_DATA,
            source_id=0x01,
            dest_id=0x10,
            payload=payload,
        )

        # Simulate wire transfer
        frame = msg.to_frame()
        received_msg = ProtocolMessage.from_frame(frame)

        # Unpack on the receiving end
        received_reading = SensorReading.from_bytes(received_msg.payload)
        assert received_reading.sensor_id == 1
        assert abs(received_reading.value - 42.5) < 0.001

    def test_batch_sensor_data_over_protocol(self):
        """Send multiple sensor readings as protocol messages through a router."""
        configs = [
            SensorConfig(sensor_id=i, name=f"Sensor_{i}", min_value=0, max_value=100,
                         warning_threshold=80, fault_threshold=95)
            for i in range(1, 4)
        ]
        processor = SensorProcessor(configs)
        router = MessageRouter()

        received_readings = []

        def handler(msg):
            reading = SensorReading.from_bytes(msg.payload)
            received_readings.append(reading)

        router.register_handler(0x10, handler)

        # Send 10 readings from different sensors
        for i in range(10):
            sid = (i % 3) + 1
            reading = SensorReading(
                sensor_id=sid, timestamp=time.time(), value=20.0 + i
            )
            processed = processor.process_reading(reading)
            msg = ProtocolMessage(
                msg_type=MessageType.SENSOR_DATA,
                source_id=sid,
                dest_id=0x10,
                payload=processed.to_bytes(),
            )
            router.send_message(msg)

        assert len(received_readings) == 10
        assert router.get_message_count() == 10


class TestBatteryWithSensors:
    """Test battery management driven by sensor data."""

    def test_battery_voltage_from_sensor_pipeline(self):
        """
        Simulate: sensor readings → processor → BMS update.
        This models the real firmware flow where ADC data goes through
        the sensor pipeline before reaching the BMS.
        """
        # Setup sensor configs for 4 cell voltage sensors
        configs = [
            SensorConfig(
                sensor_id=i, name=f"Cell_{i}_V", min_value=0, max_value=5.0,
                warning_threshold=4.1, fault_threshold=4.3,
            )
            for i in range(4)
        ]
        processor = SensorProcessor(configs)

        # Setup BMS
        pack = BatteryPack(pack_id=1)
        bms = BatteryManager(pack)

        # Simulate 100 update cycles
        for cycle in range(100):
            voltages = [3.7 + (cycle * 0.001)] * 4  # slowly rising
            cells = []
            for i in range(4):
                reading = SensorReading(
                    sensor_id=i, timestamp=time.time(), value=voltages[i]
                )
                processed = processor.process_reading(reading)
                cells.append(CellData(
                    cell_id=i, voltage=processed.value, temperature=25.0
                ))
            bms.update(cells, current=5.0)

        # After 100 cycles at 3.7 → 3.8V, should be healthy and charging
        assert bms.is_safe_to_operate()
        assert bms.pack.state == BatteryState.CHARGING

    def test_fault_propagation_chain(self):
        """
        Test the full chain: faulty sensor → processor detects fault →
        BMS receives bad data → BMS enters fault state.
        """
        configs = [SensorConfig(
            sensor_id=0, name="Cell_0_V", min_value=0, max_value=5.0,
            warning_threshold=4.1, fault_threshold=4.3,
        )]
        processor = SensorProcessor(configs)
        pack = BatteryPack(pack_id=1)
        bms = BatteryManager(pack)

        # Send an over-voltage reading through the pipeline
        reading = SensorReading(sensor_id=0, timestamp=time.time(), value=4.5)
        processed = processor.process_reading(reading)
        assert processed.status == SensorStatus.FAULT

        # Feed into BMS
        cells = [CellData(cell_id=0, voltage=processed.value, temperature=25.0)]
        bms.update(cells, current=0.0)

        assert BatteryFault.OVER_VOLTAGE in bms.pack.active_faults
        assert not bms.is_safe_to_operate()


class TestEndToEnd:
    """Full system test: sensors → protocol → processing → BMS."""

    def test_full_telemetry_loop(self):
        """
        Simulates a complete telemetry loop:
        1. Sensor readings generated
        2. Packed into protocol messages
        3. Sent through router
        4. Unpacked and processed
        5. Fed into BMS
        """
        # Sensor pipeline
        configs = [SensorConfig(
            sensor_id=i, name=f"Cell_{i}", min_value=0, max_value=5.0,
            warning_threshold=4.1, fault_threshold=4.3,
        ) for i in range(4)]
        processor = SensorProcessor(configs)

        # Communication
        router = MessageRouter()
        bms_inbox = []
        router.register_handler(0x20, lambda msg: bms_inbox.append(msg))

        # BMS
        pack = BatteryPack(pack_id=1)
        bms = BatteryManager(pack)

        # === Run 50 telemetry cycles ===
        for cycle in range(50):
            cycle_cells = []
            for i in range(4):
                # Generate reading
                reading = SensorReading(
                    sensor_id=i, timestamp=time.time(), value=3.7
                )
                processed = processor.process_reading(reading)

                # Send over protocol
                msg = ProtocolMessage(
                    msg_type=MessageType.SENSOR_DATA,
                    source_id=i,
                    dest_id=0x20,
                    payload=processed.to_bytes(),
                )
                router.send_message(msg)

                # BMS side: unpack
                received = SensorReading.from_bytes(bms_inbox[-1].payload)
                cycle_cells.append(CellData(
                    cell_id=i, voltage=received.value, temperature=25.0
                ))

            bms.update(cycle_cells, current=-5.0)

        # Verify end state
        assert bms.is_safe_to_operate()
        assert bms.pack.state == BatteryState.DISCHARGING
        assert router.get_message_count() == 200  # 4 sensors × 50 cycles
        assert len(bms_inbox) == 200
