"""
test_battery_manager.py
Unit tests for the Battery Management System module.
"""

import pytest
from sensor_pipeline.battery_manager import (
    BatteryManager,
    BatteryPack,
    CellData,
    BatteryState,
    BatteryFault,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

def make_cells(num=4, voltage=3.7, temperature=25.0):
    return [
        CellData(cell_id=i, voltage=voltage, temperature=temperature)
        for i in range(num)
    ]


@pytest.fixture
def healthy_pack():
    return BatteryPack(pack_id=1, cells=make_cells())


@pytest.fixture
def manager(healthy_pack):
    return BatteryManager(healthy_pack)


# ─── Test: Normal Operation ──────────────────────────────────────────────────

class TestNormalOperation:
    def test_idle_state(self, manager):
        cells = make_cells()
        pack = manager.update(cells, current=0.0)
        assert pack.state == BatteryState.IDLE

    def test_charging_state(self, manager):
        cells = make_cells()
        pack = manager.update(cells, current=10.0)
        assert pack.state == BatteryState.CHARGING

    def test_discharging_state(self, manager):
        cells = make_cells()
        pack = manager.update(cells, current=-10.0)
        assert pack.state == BatteryState.DISCHARGING

    def test_total_voltage_calculation(self, manager):
        cells = make_cells(num=4, voltage=3.7)
        pack = manager.update(cells, current=0.0)
        assert abs(pack.total_voltage - 14.8) < 0.01

    def test_safe_to_operate_healthy(self, manager):
        manager.update(make_cells(), current=0.0)
        assert manager.is_safe_to_operate() is True


# ─── Test: Voltage Faults ───────────────────────────────────────────────────

class TestVoltageFaults:
    def test_over_voltage_fault(self, manager):
        cells = make_cells(voltage=4.3)  # Above 4.2V max
        pack = manager.update(cells, current=0.0)
        assert BatteryFault.OVER_VOLTAGE in pack.active_faults
        assert pack.state == BatteryState.FAULT

    def test_under_voltage_fault(self, manager):
        cells = make_cells(voltage=2.5)  # Below 2.8V min
        pack = manager.update(cells, current=0.0)
        assert BatteryFault.UNDER_VOLTAGE in pack.active_faults
        assert pack.state == BatteryState.FAULT

    def test_voltage_at_max_boundary(self, manager):
        cells = make_cells(voltage=4.2)  # Exactly at max
        pack = manager.update(cells, current=0.0)
        assert BatteryFault.OVER_VOLTAGE not in pack.active_faults

    def test_voltage_at_min_boundary(self, manager):
        cells = make_cells(voltage=2.8)  # Exactly at min
        pack = manager.update(cells, current=0.0)
        assert BatteryFault.UNDER_VOLTAGE not in pack.active_faults

    def test_not_safe_on_over_voltage(self, manager):
        cells = make_cells(voltage=4.5)
        manager.update(cells, current=0.0)
        assert manager.is_safe_to_operate() is False


# ─── Test: Temperature Faults ───────────────────────────────────────────────

class TestTemperatureFaults:
    def test_over_temperature(self, manager):
        cells = make_cells(temperature=65.0)
        pack = manager.update(cells, current=0.0)
        assert BatteryFault.OVER_TEMPERATURE in pack.active_faults

    def test_under_temperature(self, manager):
        cells = make_cells(temperature=-25.0)
        pack = manager.update(cells, current=0.0)
        assert BatteryFault.UNDER_TEMPERATURE in pack.active_faults

    def test_normal_temperature(self, manager):
        cells = make_cells(temperature=25.0)
        pack = manager.update(cells, current=0.0)
        assert BatteryFault.OVER_TEMPERATURE not in pack.active_faults
        assert BatteryFault.UNDER_TEMPERATURE not in pack.active_faults


# ─── Test: Current Faults ───────────────────────────────────────────────────

class TestCurrentFaults:
    def test_over_current_charging(self, manager):
        cells = make_cells()
        pack = manager.update(cells, current=150.0)
        assert BatteryFault.OVER_CURRENT in pack.active_faults

    def test_over_current_discharging(self, manager):
        cells = make_cells()
        pack = manager.update(cells, current=-150.0)
        assert BatteryFault.OVER_CURRENT in pack.active_faults

    def test_normal_current(self, manager):
        cells = make_cells()
        pack = manager.update(cells, current=50.0)
        assert BatteryFault.OVER_CURRENT not in pack.active_faults


# ─── Test: Cell Imbalance ───────────────────────────────────────────────────

class TestCellImbalance:
    def test_imbalanced_cells(self, manager):
        cells = [
            CellData(cell_id=0, voltage=3.7, temperature=25.0),
            CellData(cell_id=1, voltage=3.7, temperature=25.0),
            CellData(cell_id=2, voltage=3.7, temperature=25.0),
            CellData(cell_id=3, voltage=3.5, temperature=25.0),  # 0.2V lower
        ]
        pack = manager.update(cells, current=0.0)
        assert BatteryFault.CELL_IMBALANCE in pack.active_faults
        assert pack.state == BatteryState.BALANCING

    def test_balanced_cells(self, manager):
        cells = make_cells(voltage=3.7)
        pack = manager.update(cells, current=0.0)
        assert BatteryFault.CELL_IMBALANCE not in pack.active_faults

    def test_voltage_spread(self, manager):
        cells = [
            CellData(cell_id=0, voltage=3.8, temperature=25.0),
            CellData(cell_id=1, voltage=3.6, temperature=25.0),
        ]
        manager.update(cells, current=0.0)
        spread = manager.get_cell_voltage_spread()
        assert abs(spread - 0.2) < 0.001


# ─── Test: SOC Estimation ───────────────────────────────────────────────────

class TestSOC:
    def test_soc_decreases_on_discharge(self, manager):
        initial_soc = manager.pack.soc
        manager.update(make_cells(), current=-50.0)
        assert manager.pack.soc < initial_soc

    def test_soc_increases_on_charge(self, manager):
        manager.pack.soc = 50.0
        manager.update(make_cells(), current=50.0)
        assert manager.pack.soc > 50.0

    def test_soc_clamped_at_zero(self, manager):
        manager.pack.soc = 0.1
        manager.update(make_cells(), current=-9999.0)
        assert manager.pack.soc >= 0.0

    def test_soc_clamped_at_hundred(self, manager):
        manager.pack.soc = 99.9
        manager.update(make_cells(), current=9999.0)
        assert manager.pack.soc <= 100.0

    def test_shutdown_on_critical_soc(self, manager):
        manager.pack.soc = 3.0  # Below 5% critical
        manager.update(make_cells(), current=-10.0)
        assert manager.pack.state == BatteryState.SHUTDOWN


# ─── Test: Helper Methods ───────────────────────────────────────────────────

class TestHelperMethods:
    def test_weakest_cell(self, manager):
        cells = [
            CellData(cell_id=0, voltage=3.8, temperature=25.0),
            CellData(cell_id=1, voltage=3.5, temperature=25.0),
            CellData(cell_id=2, voltage=3.7, temperature=25.0),
        ]
        manager.update(cells, current=0.0)
        weakest = manager.get_weakest_cell()
        assert weakest.cell_id == 1

    def test_hottest_cell(self, manager):
        cells = [
            CellData(cell_id=0, voltage=3.7, temperature=25.0),
            CellData(cell_id=1, voltage=3.7, temperature=45.0),
            CellData(cell_id=2, voltage=3.7, temperature=30.0),
        ]
        manager.update(cells, current=0.0)
        hottest = manager.get_hottest_cell()
        assert hottest.cell_id == 1

    def test_empty_cells_weakest(self, manager):
        manager.update([], current=0.0)
        assert manager.get_weakest_cell() is None

    def test_fault_history_persists(self, manager):
        manager.update(make_cells(voltage=4.5), current=0.0)
        manager.update(make_cells(voltage=3.7), current=0.0)  # clears active
        assert len(manager.fault_history) > 0
