from datetime import datetime, timedelta
import time
import json
from homeassistant.const import (
    ATTR_LOCKED,
    UnitOfEnergy,
    PERCENTAGE,
    UnitOfPower,
)
from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
    SensorDeviceClass,
)
from homeassistant.core import HomeAssistant
import logging
from typing import Any, Callable, Dict, Optional, Union
from unittest.mock import MagicMock

from .const import (
    DOMAIN,
    HEATER_NODE_TYPE_ACM,
    HEATER_NODE_TYPE_HTR,
    HEATER_NODE_TYPE_HTR_MOD,
    SMARTBOX_NODES,
)
from .model import get_temperature_unit, is_heater_node, is_heating,  SmartboxNode

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: Dict[Any, Any],
    async_add_entities: Callable,
    discovery_info: Optional[Dict[Any, Any]] = None,
) -> None:
    """Set up platform."""
    _LOGGER.debug("Setting up Smartbox sensor platform")
    if discovery_info is None:
        return

    # Temperature
    async_add_entities(
        [
            TemperatureSensor(node)
            for node in hass.data[DOMAIN][SMARTBOX_NODES]
            if is_heater_node(node)
        ],
        True,
    )
    # Power
    async_add_entities(
        [
            PowerSensor(node)
            for node in hass.data[DOMAIN][SMARTBOX_NODES]
            if is_heater_node(node) and node.node_type != HEATER_NODE_TYPE_HTR_MOD
        ],
        True,
    )
    # Duty Cycle and Energy
    # Only nodes of type 'htr' seem to report the duty cycle, which is needed
    # to compute energy consumption
    async_add_entities(
        [
            DutyCycleSensor(node)
            for node in hass.data[DOMAIN][SMARTBOX_NODES]
            if node.node_type == HEATER_NODE_TYPE_HTR
        ],
        True,
    )

    # to collect the records for cumulative electricty consumption
    async_add_entities(
        [
            SamplesSensor(node)
            for node in hass.data[DOMAIN][SMARTBOX_NODES]
            if node.node_type == HEATER_NODE_TYPE_HTR
        ],
        True,
    )
    
    async_add_entities(
        [
            KwhHourSensor(node)
            for node in hass.data[DOMAIN][SMARTBOX_NODES]
            if node.node_type == HEATER_NODE_TYPE_HTR
        ],
        True,
    )
    # Charge Level
    async_add_entities(
        [
            ChargeLevelSensor(node)
            for node in hass.data[DOMAIN][SMARTBOX_NODES]
            if is_heater_node(node) and node.node_type == HEATER_NODE_TYPE_ACM
        ],
        True,
    )

    _LOGGER.debug("Finished setting up Smartbox sensor platform")


class SmartboxSensorBase(SensorEntity):
    def __init__(self, node: Union[SmartboxNode, MagicMock]) -> None:
        self._node = node
        self._status: Dict[str, Any] = {}
        self._available = False  # unavailable until we get an update
        self._samples: Dict[str, Any] = {}
        self._last_update: Optional[datetime] = None
        self._time_since_last_update: Optional[timedelta] = None
        _LOGGER.debug(f"Created node {self.name} unique_id={self.unique_id}")

    @property
    def extra_state_attributes(self) -> Dict[str, bool]:
        return {
            ATTR_LOCKED: self._status["locked"],
        }

    @property
    def available(self) -> bool:
        return self._available

    async def async_update(self) -> None:
        new_status = await self._node.async_update(self.hass)
        if new_status["sync_status"] == "ok":
            # update our status
            self._status = new_status
            self._available = True
            update_time = datetime.now()
            if self._last_update is not None:
                self._time_since_last_update = update_time - self._last_update
            self._last_update = update_time
        else:
            self._available = False
            self._last_update = None
            self._time_since_last_update = None

    @property
    def time_since_last_update(self) -> Optional[timedelta]:
        return self._time_since_last_update


class TemperatureSensor(SmartboxSensorBase):
    """Smartbox heater temperature sensor"""

    device_class = SensorDeviceClass.TEMPERATURE
    state_class = SensorStateClass.MEASUREMENT

    def __init__(self, node: Union[SmartboxNode, MagicMock]) -> None:
        super().__init__(node)

    @property
    def name(self) -> str:
        return f"{self._node.name} Temperature"

    @property
    def unique_id(self) -> str:
        return f"{self._node.node_id}_temperature"

    @property
    def native_value(self) -> float:
        return self._status["mtemp"]

    @property
    def native_unit_of_measurement(self) -> Any:
        return get_temperature_unit(self._status)


class PowerSensor(SmartboxSensorBase):
    """Smartbox heater power sensor

    Note: this represents the power the heater is drawing *when heating*; the
    heater is not always active over the entire period since the last update,
    even when 'active' is true. The duty cycle sensor indicates how much it
    was active. To measure energy consumption, use the corresponding energy
    sensor.
    """

    device_class = SensorDeviceClass.POWER
    native_unit_of_measurement = UnitOfPower.WATT
    state_class = SensorStateClass.MEASUREMENT

    def __init__(self, node: Union[SmartboxNode, MagicMock]) -> None:
        super().__init__(node)

    @property
    def name(self) -> str:
        return f"{self._node.name} Power"

    @property
    def unique_id(self) -> str:
        return f"{self._node.node_id}_power"

    @property
    def native_value(self) -> float:
        return (
            self._status["power"]
            if is_heating(self._node.node_type, self._status)
            else 0
        )


class DutyCycleSensor(SmartboxSensorBase):
    """Smartbox heater duty cycle sensor

    Represents the duty cycle for the heater.
    """

    device_class = SensorDeviceClass.POWER_FACTOR
    native_unit_of_measurement = PERCENTAGE
    state_class = SensorStateClass.MEASUREMENT

    def __init__(self, node: Union[SmartboxNode, MagicMock]) -> None:
        super().__init__(node)

    @property
    def name(self) -> str:
        return f"{self._node.name} Duty Cycle"

    @property
    def unique_id(self) -> str:
        return f"{self._node.node_id}_duty_cycle"

    @property
    def native_value(self) -> float:
        return self._status["duty"]


class SamplesSensor(SmartboxSensorBase):
    """Smartbox samples sensor

    Represents the cumulative electrity consumed by the heater.
    """
    
    device_class = SensorDeviceClass.ENERGY
    native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    state_class = SensorStateClass.TOTAL


    def __init__(self, node: Union[SmartboxNode, MagicMock]) -> None:
        super().__init__(node)
       

    @property
    def name(self) -> str:
        return f"{self._node.name} Cumulative KWh"

    @property
    def unique_id(self) -> str:
        return f"{self._node.node_id}_energy"

    @property
    def native_value(self) -> float | None:
       if time.time() - self._node._last_run_time > 600:
            get_samples = str(self._node._samples).replace("<Future finished result=","").replace(">","") 
            _LOGGER.debug(f"Get Samples: {get_samples}")
            self._node._samples = json.loads(get_samples.replace("'", "\""))
            _LOGGER.debug(f"Current Time: {time.time()}, Current Node Samples{self._node._samples}")
            kwh = self._node.get_energy_used(self._node._samples)
            self._node._node_samples_update(self._node.node_type, self._node.addr)
            _LOGGER.debug(f"Updated Node Samples{self._node._samples}")
            self._node._last_run_time = time.time()
            _LOGGER.debug(f"Api Start Time : {round(time.time() - time.time() % 3600) - 3600}, Last Run Time: {self._node._last_run_time - (round(time.time() - time.time() % 3600) - 3600)}")
            _LOGGER.debug(f"KWH: {kwh}")
            
            if kwh != self._node._kwh:
                 self._node._kwh = kwh
                 self._node._summation_kwh = self._node._summation_kwh + kwh
                 _LOGGER.debug(f"KWH: {self._node._kwh}, Summation KWH: {self._node._summation_kwh}")
            return self._node._summation_kwh
       else:
            _LOGGER.debug(f"KWH: {self._node._kwh}, Summation KWH: {self._node._summation_kwh}")
            return self._node._summation_kwh

class KwhHourSensor(SmartboxSensorBase):
    """Smartbox samples sensor

    Represents the cumulative electrity consumed by the heater in the last hour.
    """
    
    device_class = SensorDeviceClass.ENERGY
    native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    state_class = SensorStateClass.MEASUREMENT


    def __init__(self, node: Union[SmartboxNode, MagicMock]) -> None:
        super().__init__(node) 

    @property
    def name(self) -> str:
        return f"{self._node.name} Hourly KWh"

    @property
    def unique_id(self) -> str:
        return f"{self._node.node_id}_energy_hour"

    @property
    def native_value(self) -> float | None:
        return self._node._kwh
        

class ChargeLevelSensor(SmartboxSensorBase):
    """Smartbox storage heater charge level sensor"""

    device_class = SensorDeviceClass.BATTERY
    native_unit_of_measurement = PERCENTAGE
    state_class = SensorStateClass.MEASUREMENT

    def __init__(self, node: Union[SmartboxNode, MagicMock]) -> None:
        super().__init__(node)

    @property
    def name(self) -> str:
        return f"{self._node.name} Charge Level"

    @property
    def unique_id(self) -> str:
        return f"{self._node.node_id}_charge_level"

    @property
    def native_value(self) -> int:
        return self._status["charge_level"]

