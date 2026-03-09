"""
test_comm_protocol.py
Unit tests for the communication protocol layer.
"""

import pytest
from sensor_pipeline.comm_protocol import (
    ProtocolMessage,
    MessageType,
    MessageRouter,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_message():
    return ProtocolMessage(
        msg_type=MessageType.SENSOR_DATA,
        source_id=0x01,
        dest_id=0x02,
        payload=b"\x10\x20\x30\x40",
    )


@pytest.fixture
def router():
    return MessageRouter()


# ─── Test: Frame Serialization ───────────────────────────────────────────────

class TestFrameSerialization:
    def test_round_trip(self, sample_message):
        frame = sample_message.to_frame()
        restored = ProtocolMessage.from_frame(frame)
        assert restored.msg_type == sample_message.msg_type
        assert restored.source_id == sample_message.source_id
        assert restored.dest_id == sample_message.dest_id
        assert restored.payload == sample_message.payload

    def test_start_byte(self, sample_message):
        frame = sample_message.to_frame()
        assert frame[0] == ProtocolMessage.START_BYTE

    def test_end_byte(self, sample_message):
        frame = sample_message.to_frame()
        assert frame[-1] == ProtocolMessage.END_BYTE

    def test_all_message_types(self):
        for msg_type in MessageType:
            msg = ProtocolMessage(
                msg_type=msg_type, source_id=1, dest_id=2, payload=b"\x00"
            )
            frame = msg.to_frame()
            restored = ProtocolMessage.from_frame(frame)
            assert restored.msg_type == msg_type

    def test_empty_payload(self):
        msg = ProtocolMessage(
            msg_type=MessageType.HEARTBEAT, source_id=1, dest_id=2, payload=b""
        )
        frame = msg.to_frame()
        restored = ProtocolMessage.from_frame(frame)
        assert restored.payload == b""

    def test_large_payload(self):
        payload = bytes(range(256)) * 4  # 1024 bytes
        msg = ProtocolMessage(
            msg_type=MessageType.SENSOR_DATA, source_id=1, dest_id=2, payload=payload
        )
        frame = msg.to_frame()
        restored = ProtocolMessage.from_frame(frame)
        assert restored.payload == payload


# ─── Test: Frame Validation ──────────────────────────────────────────────────

class TestFrameValidation:
    def test_frame_too_short(self):
        with pytest.raises(ValueError, match="too short"):
            ProtocolMessage.from_frame(b"\xAA\x01\x02")

    def test_invalid_start_byte(self):
        frame = b"\xFF" + b"\x00" * 9
        with pytest.raises(ValueError, match="Invalid start byte"):
            ProtocolMessage.from_frame(frame)

    def test_invalid_end_byte(self, sample_message):
        frame = bytearray(sample_message.to_frame())
        frame[-1] = 0x00  # corrupt end byte
        with pytest.raises(ValueError, match="Invalid end byte"):
            ProtocolMessage.from_frame(bytes(frame))

    def test_crc_corruption(self, sample_message):
        frame = bytearray(sample_message.to_frame())
        frame[-2] ^= 0xFF  # flip bits in CRC
        with pytest.raises(ValueError, match="CRC mismatch"):
            ProtocolMessage.from_frame(bytes(frame))

    def test_payload_corruption(self, sample_message):
        frame = bytearray(sample_message.to_frame())
        frame[8] ^= 0xFF  # flip a payload byte
        with pytest.raises(ValueError, match="CRC mismatch"):
            ProtocolMessage.from_frame(bytes(frame))


# ─── Test: CRC ───────────────────────────────────────────────────────────────

class TestCRC:
    def test_crc_deterministic(self):
        data = b"hello world"
        crc1 = ProtocolMessage._compute_crc(data)
        crc2 = ProtocolMessage._compute_crc(data)
        assert crc1 == crc2

    def test_crc_different_data(self):
        crc1 = ProtocolMessage._compute_crc(b"hello")
        crc2 = ProtocolMessage._compute_crc(b"world")
        assert crc1 != crc2

    def test_crc_empty_data(self):
        crc = ProtocolMessage._compute_crc(b"")
        assert isinstance(crc, int)
        assert 0 <= crc <= 0xFFFF


# ─── Test: Message Router ───────────────────────────────────────────────────

class TestMessageRouter:
    def test_route_to_handler(self, router):
        received = []
        router.register_handler(0x02, lambda msg: received.append(msg))
        msg = ProtocolMessage(
            msg_type=MessageType.COMMAND, source_id=1, dest_id=2, payload=b"\x01"
        )
        router.send_message(msg)
        assert len(received) == 1
        assert received[0].dest_id == 2

    def test_no_handler(self, router):
        msg = ProtocolMessage(
            msg_type=MessageType.HEARTBEAT, source_id=1, dest_id=99, payload=b""
        )
        result = router.send_message(msg)
        assert result is None

    def test_message_logging(self, router):
        msg = ProtocolMessage(
            msg_type=MessageType.HEARTBEAT, source_id=1, dest_id=2, payload=b""
        )
        router.send_message(msg)
        router.send_message(msg)
        assert router.get_message_count() == 2

    def test_sequence_numbering(self, router):
        router.register_handler(2, lambda m: None)
        for i in range(5):
            msg = ProtocolMessage(
                msg_type=MessageType.HEARTBEAT, source_id=1, dest_id=2, payload=b""
            )
            router.send_message(msg)
        log = router.get_message_log()
        sequences = [m.sequence_num for m in log]
        assert sequences == [0, 1, 2, 3, 4]

    def test_duplicate_handler_raises(self, router):
        router.register_handler(1, lambda m: None)
        with pytest.raises(ValueError, match="already registered"):
            router.register_handler(1, lambda m: None)

    def test_clear_log(self, router):
        msg = ProtocolMessage(
            msg_type=MessageType.HEARTBEAT, source_id=1, dest_id=2, payload=b""
        )
        router.send_message(msg)
        router.clear_log()
        assert router.get_message_count() == 0
