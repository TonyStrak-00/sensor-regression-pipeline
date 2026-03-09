"""
battery_manager.py
Simulates a Battery Management System (BMS) — relevant to both Apptronik robots
and your PACCAR EV work. This models the kind of logic running on a BMS ECU.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from enum import IntEnum


class BatteryState(IntEnum):
    IDLE = 0
    CHARGING = 1
    DISCHARGING = 2
    BALANCING = 3
    FAULT = 4
    SHUTDOWN = 5


class BatteryFault(IntEnum):
    NONE = 0
    OVER_VOLTAGE = 1
    UNDER_VOLTAGE = 2
    OVER_CURRENT = 3
    OVER_TEMPERATURE = 4
    UNDER_TEMPERATURE = 5
    CELL_IMBALANCE = 6
    COMMUNICATION_LOSS = 7


@dataclass
class CellData:
    cell_id: int
    voltage: float  # Volts
    temperature: float  # Celsius
    internal_resistance: float = 0.0  # mOhms


@dataclass
class BatteryPack:
    pack_id: int
    cells: List[CellData] = field(default_factory=list)
    total_voltage: float = 0.0
    current: float = 0.0  # Amps (positive = charging, negative = discharging)
    soc: float = 100.0  # State of Charge (%)
    state: BatteryState = BatteryState.IDLE
    active_faults: List[BatteryFault] = field(default_factory=list)


class BatteryManager:
    """
    BMS logic: monitors cells, detects faults, manages charging state.
    Models what runs on the BMS microcontroller in real firmware.
    """

    # Thresholds — these would normally come from calibration data
    CELL_VOLTAGE_MAX = 4.2  # V
    CELL_VOLTAGE_MIN = 2.8  # V
    CELL_VOLTAGE_NOMINAL = 3.7  # V
    CELL_TEMP_MAX = 60.0  # °C
    CELL_TEMP_MIN = -20.0  # °C
    MAX_CURRENT = 100.0  # A
    CELL_IMBALANCE_THRESHOLD = 0.05  # V
    SOC_CRITICAL = 5.0  # %

    def __init__(self, pack: BatteryPack):
        self._pack = pack
        self._fault_history: List[dict] = []
        self._cycle_count = 0

    @property
    def pack(self) -> BatteryPack:
        return self._pack

    @property
    def fault_history(self) -> List[dict]:
        return list(self._fault_history)

    def update(self, cells: List[CellData], current: float) -> BatteryPack:
        """
        Main update loop — called every control cycle (e.g., 100ms).
        Takes fresh cell data and pack current, returns updated pack state.
        """
        self._pack.cells = cells
        self._pack.current = current
        self._pack.total_voltage = sum(c.voltage for c in cells)

        # Clear previous faults and re-evaluate
        self._pack.active_faults.clear()

        # Run fault checks
        self._check_voltage_faults(cells)
        self._check_temperature_faults(cells)
        self._check_current_fault(current)
        self._check_cell_imbalance(cells)

        # Update SOC estimate (simplified coulomb counting)
        self._update_soc(current)

        # Determine state
        self._update_state()

        return self._pack

    def get_weakest_cell(self) -> Optional[CellData]:
        """Find the cell with lowest voltage."""
        if not self._pack.cells:
            return None
        return min(self._pack.cells, key=lambda c: c.voltage)

    def get_hottest_cell(self) -> Optional[CellData]:
        """Find the cell with highest temperature."""
        if not self._pack.cells:
            return None
        return max(self._pack.cells, key=lambda c: c.temperature)

    def get_cell_voltage_spread(self) -> float:
        """Voltage difference between highest and lowest cells."""
        if not self._pack.cells:
            return 0.0
        voltages = [c.voltage for c in self._pack.cells]
        return max(voltages) - min(voltages)

    def is_safe_to_operate(self) -> bool:
        """Check if pack is in a safe operating condition."""
        critical_faults = {
            BatteryFault.OVER_VOLTAGE,
            BatteryFault.UNDER_VOLTAGE,
            BatteryFault.OVER_CURRENT,
            BatteryFault.OVER_TEMPERATURE,
        }
        return not any(f in critical_faults for f in self._pack.active_faults)

    def _check_voltage_faults(self, cells: List[CellData]):
        for cell in cells:
            if cell.voltage > self.CELL_VOLTAGE_MAX:
                self._add_fault(BatteryFault.OVER_VOLTAGE, cell.cell_id, cell.voltage)
            elif cell.voltage < self.CELL_VOLTAGE_MIN:
                self._add_fault(BatteryFault.UNDER_VOLTAGE, cell.cell_id, cell.voltage)

    def _check_temperature_faults(self, cells: List[CellData]):
        for cell in cells:
            if cell.temperature > self.CELL_TEMP_MAX:
                self._add_fault(BatteryFault.OVER_TEMPERATURE, cell.cell_id, cell.temperature)
            elif cell.temperature < self.CELL_TEMP_MIN:
                self._add_fault(BatteryFault.UNDER_TEMPERATURE, cell.cell_id, cell.temperature)

    def _check_current_fault(self, current: float):
        if abs(current) > self.MAX_CURRENT:
            self._add_fault(BatteryFault.OVER_CURRENT, -1, current)

    def _check_cell_imbalance(self, cells: List[CellData]):
        if len(cells) < 2:
            return
        spread = self.get_cell_voltage_spread()
        if spread > self.CELL_IMBALANCE_THRESHOLD:
            self._add_fault(BatteryFault.CELL_IMBALANCE, -1, spread)

    def _update_soc(self, current: float):
        """Simplified SOC estimation via coulomb counting."""
        # Assuming 100ms update rate, 50Ah capacity
        capacity_ah = 50.0
        dt_hours = 0.1 / 3600.0
        delta_soc = (current * dt_hours / capacity_ah) * 100.0
        self._pack.soc = max(0.0, min(100.0, self._pack.soc + delta_soc))

    def _update_state(self):
        if self._pack.active_faults:
            critical = {BatteryFault.OVER_VOLTAGE, BatteryFault.UNDER_VOLTAGE, BatteryFault.OVER_CURRENT, BatteryFault.OVER_TEMPERATURE}
            if any(f in critical for f in self._pack.active_faults):
                self._pack.state = BatteryState.FAULT
            elif BatteryFault.CELL_IMBALANCE in self._pack.active_faults:
                self._pack.state = BatteryState.BALANCING
        elif self._pack.current > 0.1:
            self._pack.state = BatteryState.CHARGING
        elif self._pack.current < -0.1:
            self._pack.state = BatteryState.DISCHARGING
        else:
            self._pack.state = BatteryState.IDLE

        if self._pack.soc <= self.SOC_CRITICAL and self._pack.state != BatteryState.CHARGING:
            self._pack.state = BatteryState.SHUTDOWN

    def _add_fault(self, fault: BatteryFault, cell_id: int, value: float):
        if fault not in self._pack.active_faults:
            self._pack.active_faults.append(fault)
        self._fault_history.append({
            "fault": fault,
            "cell_id": cell_id,
            "value": value,
            "pack_soc": self._pack.soc,
        })
