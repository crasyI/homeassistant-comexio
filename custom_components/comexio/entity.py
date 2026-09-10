# Version: 0.7.8
import logging
from typing import Any

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SOURCE_CATEGORIES, WebioClass
from .coordinator import ComexioCoordinator

_LOGGER = logging.getLogger(__name__)


def hub_device_id(coordinator: ComexioCoordinator) -> str | None:
    """Resolve the hub device's registry id for via_device_id linkage.

    Returns None (instead of raising) if the hub device isn't registered yet, so a
    dependent entity still gets created — just without the via_device_id link — rather
    than having its whole platform setup aborted by an uncaught ValueError.
    """
    try:
        return dr.async_get_device_id_by_identifier(
            coordinator.hass, (DOMAIN, coordinator.server_id), config_entry_id=coordinator.config_entry.entry_id
        )
    except ValueError:
        _LOGGER.error(
            "Hub device for server '%s' (entry %s) not found in the device registry; "
            "affected entities will be created without a via_device_id link",
            coordinator.server_id,
            coordinator.config_entry.entry_id,
        )
        return None


def build_device_info(
    coordinator: ComexioCoordinator, *, identifiers: set[tuple[str, str]], name: str, model: str
) -> DeviceInfo:
    """Build a sub-device's device_info, linked to the hub device via via_device_id."""
    info: DeviceInfo = {
        "identifiers": identifiers,
        "name": name,
        "manufacturer": "Comexio",
        "model": model,
    }
    if via_id := hub_device_id(coordinator):
        info["via_device_id"] = via_id
    return info


class ComexioIOEntity(CoordinatorEntity):
    """Shared base for all IO entities attached to an extension module.

    Centralises device_info and offline-availability logic that would otherwise
    be duplicated across sensor, switch, and binary_sensor platforms.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: ComexioCoordinator, server_id: str, io: dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._io_id: str = io["id"]
        self._ext_name: str = io["ext_name"]
        self._attr_unique_id = f"comexio_{server_id}_{io['ext_name']}_{io['identifier']}".lower()
        self._attr_name = io["ha_name"]

    @property
    def device_info(self) -> DeviceInfo:
        return build_device_info(
            self.coordinator,
            identifiers={(DOMAIN, f"{self.coordinator.server_id}_{self._ext_name}".lower())},
            name=f"{self.coordinator.server_id} {self._ext_name}",
            model="Extension Module",
        )

    @property
    def available(self) -> bool:
        return super().available and self._ext_name not in self.coordinator.offline_extensions


class ComexioMarkerEntity(CoordinatorEntity):
    """Shared base for all marker entities (writable and read-only).

    Centralises unique_id/name/device_info that would otherwise be duplicated
    across the switch, number, binary_sensor, and sensor platforms.

    Markers and KNX objects are near-identical twins (see const.SOURCE_CATEGORIES):
    the three coordinator/API touch-points a domain entity needs — value read, HA
    write, cache update — are routed through the _source_* helpers below, keyed on
    the ``_SOURCE`` class attribute, so ComexioKnxEntity can reuse every domain
    subclass unchanged by just flipping ``_SOURCE``.
    """

    _attr_has_entity_name = True
    _SOURCE: WebioClass = WebioClass.MARKER

    def __init__(self, coordinator: ComexioCoordinator, server_id: str, marker: dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._marker_id = str(marker["id"])
        infix = SOURCE_CATEGORIES[self._SOURCE].unique_id_infix
        self._attr_unique_id = f"comexio_{server_id}_{infix}{self._marker_id}".lower()
        self._attr_name = marker["ha_name"]

    @property
    def _source_label(self) -> str:
        """Short category label ('Marker'/'KNX') for user-facing error messages."""
        return SOURCE_CATEGORIES[self._SOURCE].label

    @property
    def _source_value(self) -> Any:
        """Latest cached value for this source, or None if unknown."""
        return self.coordinator.source_states(self._SOURCE).get(self._marker_id)

    async def _async_source_write(self, value: float | int) -> bool:
        """Push a value to Comexio via the API (marker/KNX write path)."""
        return await self.coordinator.api.set_value(self._SOURCE.value, self._marker_id, value)

    def _source_cache_update(self, value: float | int) -> None:
        """Optimistically update the coordinator's value cache after a write."""
        self.coordinator.update_source(self._SOURCE, self._marker_id, value)

    @property
    def device_info(self) -> DeviceInfo:
        return build_device_info(
            self.coordinator,
            identifiers={(DOMAIN, f"{self.coordinator.server_id}_markers")},
            name=f"{self.coordinator.server_id} Markers",
            model="Marker Group",
        )


class ComexioKnxEntity(ComexioMarkerEntity):
    """Shared base for all KNX-object entities (blind implementation, see project_knx_objects memory).

    KNX objects are modeled 1:1 on markers; only the unique_id infix ('k', via
    SOURCE_CATEGORIES) and the sub-device grouping differ, so every ComexioMarker*
    domain subclass works for KNX by additionally inheriting from this mixin.
    """

    _SOURCE = WebioClass.KNX

    @property
    def device_info(self) -> DeviceInfo:
        return build_device_info(
            self.coordinator,
            identifiers={(DOMAIN, f"{self.coordinator.server_id}_knx")},
            name=f"{self.coordinator.server_id} KNX",
            model="KNX Group",
        )
