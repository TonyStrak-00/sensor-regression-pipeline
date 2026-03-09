"""
comm_protocol.py
Simulates a simplified communication protocol layer (like CAN or UART framing).
"""

import struct
from dataclasses import dataclass
from typing import List, Optional
from enum import IntEnum


class MessageType(IntEnum):
    HEARTBEAT = 0x01
    SENSOR_DATA = 0x02
    COMMAND = 0x03
    ACK = 0x04
    ERROR = 0xFF


@dataclass
class ProtocolMessage:
    msg_type: MessageType
    source_id: int
    dest_id: int
    payload: bytes
    sequence_num: int = 0

    # Frame format: [START(1)] [TYPE(1)] [SRC(1)] [DST(1)] [SEQ(2)] [LEN(2)] [PAYLOAD(N)] [CRC(2)] [END(1)]
    START_BYTE = 0xAA
    END_BYTE = 0x55

    def to_frame(self) -> bytes:
        """Serialize message into a wire frame with CRC."""
        header = struct.pack(
            "<BBBBBH",
            self.START_BYTE,
            int(self.msg_type),
            self.source_id,
            self.dest_id,
            self.sequence_num & 0xFF,
            len(self.payload),
        )
        crc = self._compute_crc(header[1:] + self.payload)
        return header + self.payload + struct.pack("<H", crc) + bytes([self.END_BYTE])

    @classmethod
    def from_frame(cls, data: bytes) -> "ProtocolMessage":
        """Deserialize a wire frame back into a message."""
        if len(data) < 10:
            raise ValueError(f"Frame too short: {len(data)} bytes")
        if data[0] != cls.START_BYTE:
            raise ValueError(f"Invalid start byte: 0x{data[0]:02X}")
        if data[-1] != cls.END_BYTE:
            raise ValueError(f"Invalid end byte: 0x{data[-1]:02X}")

        msg_type, source_id, dest_id, seq, payload_len = struct.unpack(
            "<BBBBBH", data[:7]
        )

        if len(data) != 7 + payload_len + 3:
            raise ValueError(
                f"Frame length mismatch: expected {7 + payload_len + 3}, got {len(data)}"
            )

        payload = data[7 : 7 + payload_len]
        received_crc = struct.unpack("<H", data[7 + payload_len : 9 + payload_len])[0]

        # Verify CRC
        computed_crc = cls._compute_crc(data[1:7] + payload)
        if received_crc != computed_crc:
            raise ValueError(
                f"CRC mismatch: received 0x{received_crc:04X}, computed 0x{computed_crc:04X}"
            )

        return cls(
            msg_type=MessageType(msg_type),
            source_id=source_id,
            dest_id=dest_id,
            payload=payload,
            sequence_num=seq,
        )

    @staticmethod
    def _compute_crc(data: bytes) -> int:
        """CRC-16/CCITT - commonly used in embedded protocols."""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ 0x1021
                else:
                    crc <<= 1
                crc &= 0xFFFF
        return crc


class MessageRouter:
    """Routes messages between nodes — simulates a CAN bus or UART multiplexer."""

    def __init__(self):
        self._handlers: dict = {}
        self._message_log: List[ProtocolMessage] = []
        self._sequence_counters: dict = {}

    def register_handler(self, dest_id: int, handler: callable):
        """Register a handler for messages to a specific destination."""
        if dest_id in self._handlers:
            raise ValueError(f"Handler already registered for dest_id {dest_id}")
        self._handlers[dest_id] = handler

    def send_message(self, msg: ProtocolMessage) -> Optional[ProtocolMessage]:
        """Send a message and return any response."""
        # Assign sequence number
        src = msg.source_id
        if src not in self._sequence_counters:
            self._sequence_counters[src] = 0
        msg.sequence_num = self._sequence_counters[src]
        self._sequence_counters[src] = (self._sequence_counters[src] + 1) & 0xFF

        # Serialize and deserialize to simulate wire transfer
        frame = msg.to_frame()
        received = ProtocolMessage.from_frame(frame)
        self._message_log.append(received)

        # Route to handler
        handler = self._handlers.get(received.dest_id)
        if handler:
            return handler(received)
        return None

    def get_message_log(self) -> List[ProtocolMessage]:
        return list(self._message_log)

    def get_message_count(self) -> int:
        return len(self._message_log)

    def clear_log(self):
        self._message_log.clear()
