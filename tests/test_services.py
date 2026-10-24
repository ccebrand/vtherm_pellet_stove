# pylint: disable=protected-access

"""Home Assistant service registration, validation and lifecycle tests."""

import json
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol
import yaml
from homeassistant.core import Context
from homeassistant.exceptions import ServiceValidationError, Unauthorized, UnknownUser
from homeassistant.helpers import entity_registry as er

from custom_components.vtherm_pellet_stove.const import (
    CONF_MIN_ON_DURATION_MIN,
    CONF_TARGET_VTHERM,
    DATA_HANDLERS,
    DATA_LOADED_ENTRIES,
    DOMAIN,
    SERVICE_RESET,
)
from custom_components.vtherm_pellet_stove.handler import PelletRegulationHandler
from custom_components.vtherm_pellet_stove.sensor import PelletDebugSensor


@pytest.fixture(name="integration")
def integration_module(monkeypatch):
    """Execute the real setup module without importing the VTherm dependency."""
    package = "custom_components.vtherm_pellet_stove"
    monkeypatch.setitem(sys.modules, "vtherm_api.vtherm_api", MagicMock())
    monkeypatch.setitem(sys.modules, f"{package}.factory", MagicMock())
    path = Path(__file__).parents[1] / "custom_components/vtherm_pellet_stove/__init__.py"
    spec = spec_from_file_location(package, path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_register_factory", MagicMock())
    monkeypatch.setattr(module, "_reload_pellet_vtherms", AsyncMock())
    return module


async def _setup_service(hass, integration):
    entry = MagicMock(entry_id="plugin", unique_id="plugin")
    await integration.async_setup_entry(hass, entry)


def _target(hass, unique_id="pellet_test", platform="versatile_thermostat"):
    entry = er.async_get(hass).async_get_or_create("climate", platform, unique_id)
    hass.states.async_set(entry.entity_id, "off")
    handler = SimpleNamespace(async_reset=AsyncMock())
    hass.data.setdefault(DOMAIN, {}).setdefault(DATA_HANDLERS, {})[unique_id] = handler
    return entry.entity_id, handler


async def test_reset_targets_one_active_handler(hass, integration):
    """Global-defaults-only handlers are targetable and isolated."""
    entity_id, handler = _target(hass)
    _, other = _target(hass, "other")
    await _setup_service(hass, integration)
    await _setup_service(hass, integration)
    context = Context()

    await hass.services.async_call(
        DOMAIN, SERVICE_RESET, {"entity_id": entity_id}, blocking=True, context=context
    )

    handler.async_reset.assert_awaited_once_with(context)
    other.async_reset.assert_not_awaited()


@pytest.mark.parametrize("data", [{}, {"entity_id": []}, {"entity_id": ["climate.one", "climate.two"]}])
async def test_reset_requires_one_explicit_target(hass, integration, data):
    await _setup_service(hass, integration)
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(DOMAIN, SERVICE_RESET, data, blocking=True)


@pytest.mark.parametrize("kind", ["missing", "non_pellet", "underlying", "unavailable", "unknown"])
async def test_invalid_target_does_not_reset(hass, integration, kind):
    entity_id, handler = _target(hass, platform="duepi_evo" if kind == "underlying" else "versatile_thermostat")
    if kind == "missing":
        hass.states.async_remove(entity_id)
    elif kind == "non_pellet":
        hass.data[DOMAIN][DATA_HANDLERS].clear()
    elif kind in ("unavailable", "unknown"):
        hass.states.async_set(entity_id, kind)
    await _setup_service(hass, integration)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_RESET, {"entity_id": entity_id}, blocking=True
        )
    handler.async_reset.assert_not_awaited()


@pytest.mark.parametrize("known_user", [False, True])
async def test_reset_checks_control_permission(hass, integration, monkeypatch, known_user):
    entity_id, handler = _target(hass)
    user = MagicMock() if known_user else None
    if user is not None:
        user.permissions.check_entity.return_value = False
    monkeypatch.setattr(hass.auth, "async_get_user", AsyncMock(return_value=user))
    await _setup_service(hass, integration)

    with pytest.raises(Unauthorized if known_user else UnknownUser):
        await hass.services.async_call(
            DOMAIN, SERVICE_RESET, {"entity_id": entity_id},
            blocking=True, context=Context(user_id="test_user"),
        )
    handler.async_reset.assert_not_awaited()


async def test_service_lifecycle_ignores_handler_and_sensor_keys(hass, integration, monkeypatch):
    """Only loaded plugin entries determine when the service is removed."""
    monkeypatch.setattr(integration, "_register_factory", MagicMock())
    unregister = MagicMock()
    monkeypatch.setattr(integration, "_unregister_factory", unregister)
    monkeypatch.setattr(integration, "_reload_pellet_vtherms", AsyncMock())
    entries = [MagicMock(entry_id=key, unique_id=key) for key in ("first", "second")]
    for entry in entries:
        await integration.async_setup_entry(hass, entry)
    hass.data[DOMAIN]["debug_sensor_test"] = object()
    _target(hass)

    assert await integration.async_unload_entry(hass, entries[0])
    assert hass.services.has_service(DOMAIN, SERVICE_RESET)
    unregister.assert_not_called()
    assert await integration.async_unload_entry(hass, entries[1])
    assert not hass.services.has_service(DOMAIN, SERVICE_RESET)
    unregister.assert_called_once()
    await integration.async_setup_entry(hass, entries[0])
    assert hass.services.has_service(DOMAIN, SERVICE_RESET)


@pytest.mark.xfail(
    strict=True,
    reason="Issue #7: live handler has no safe options-update contract yet",
)
async def test_local_options_reload_does_not_reload_vtherm(hass, integration, monkeypatch):
    """Local Options updates a live handler without reloading its VTherm."""
    global_entry = MagicMock(
        entry_id="global-plugin",
        unique_id=DOMAIN,
        data={},
        options={CONF_MIN_ON_DURATION_MIN: 30},
    )
    entry = MagicMock(
        entry_id="local-plugin",
        unique_id=f"{DOMAIN}-vt_uid",
        data={CONF_TARGET_VTHERM: "vt_uid"},
        options={CONF_MIN_ON_DURATION_MIN: 10},
    )
    hass.config_entries.async_entries = MagicMock(return_value=[global_entry, entry])
    thermostat = MagicMock(
        hass=hass,
        unique_id="vt_uid",
        name="Test VTherm",
    )
    handler = PelletRegulationHandler(thermostat)
    handler.init_algorithm()
    sensor = PelletDebugSensor(thermostat)
    handler._debug_sensor = sensor
    sensor.update_from_controller(handler._controller)
    hass.data.setdefault(DOMAIN, {})[DATA_HANDLERS] = {"vt_uid": handler}
    hass.data[DOMAIN][DATA_LOADED_ENTRIES] = {"global-plugin"}

    async def reload_local_entry(entry_id):
        assert entry_id == entry.entry_id
        await integration.async_unload_entry(hass, entry)
        await integration.async_setup_entry(hass, entry)

    reload_entry = AsyncMock(side_effect=reload_local_entry)
    monkeypatch.setattr(hass.config_entries, "async_reload", reload_entry)
    entry.options = {CONF_MIN_ON_DURATION_MIN: 42}

    await integration._async_update_options(hass, entry)

    reload_entry.assert_awaited_once_with(entry.entry_id)
    integration._reload_pellet_vtherms.assert_not_awaited()
    assert sensor.native_value != "unknown"
    assert sensor.extra_state_attributes
    assert {
        "handler": handler._controller._guard.min_on_duration_min,
        "diagnostic": sensor.extra_state_attributes["min_on_duration_min"],
    } == {"handler": 42, "diagnostic": 42}


@pytest.mark.xfail(
    strict=True,
    reason="Issue #7: unloading the last plugin entry currently reloads VTherm",
)
async def test_local_options_reload_without_global_keeps_vtherm_running(
    hass, integration, monkeypatch
):
    """Options reload must not reload VTherm when the local entry is the only one."""
    entry = MagicMock(
        entry_id="local-plugin",
        unique_id=f"{DOMAIN}-vt_uid",
        data={CONF_TARGET_VTHERM: "vt_uid"},
        options={},
    )
    monkeypatch.setattr(integration, "_unregister_factory", MagicMock())

    async def reload_local_entry(entry_id):
        assert entry_id == entry.entry_id
        await integration.async_unload_entry(hass, entry)
        await integration.async_setup_entry(hass, entry)

    reload_entry = AsyncMock(side_effect=reload_local_entry)
    monkeypatch.setattr(hass.config_entries, "async_reload", reload_entry)
    await integration.async_setup_entry(hass, entry)

    await integration._async_update_options(hass, entry)

    integration._reload_pellet_vtherms.assert_not_awaited()


async def test_failed_global_setup_does_not_register_service(hass, integration, monkeypatch):
    setup = AsyncMock(side_effect=RuntimeError("platform failed"))
    monkeypatch.setattr(hass.config_entries, "async_forward_entry_setups", setup)
    entry = MagicMock(entry_id="global", unique_id=DOMAIN)
    with pytest.raises(RuntimeError, match="platform failed"):
        await integration.async_setup_entry(hass, entry)
    assert not hass.services.has_service(DOMAIN, SERVICE_RESET)


async def test_failed_global_unload_keeps_service(hass, integration, monkeypatch):
    monkeypatch.setattr(hass.config_entries, "async_forward_entry_setups", AsyncMock())
    monkeypatch.setattr(
        hass.config_entries, "async_unload_platforms", AsyncMock(return_value=False)
    )
    entry = MagicMock(entry_id="global", unique_id=DOMAIN)
    await integration.async_setup_entry(hass, entry)
    assert not await integration.async_unload_entry(hass, entry)
    assert hass.services.has_service(DOMAIN, SERVICE_RESET)


def test_reset_metadata_is_valid_and_translated():
    root = Path(__file__).parents[1] / "custom_components/vtherm_pellet_stove"
    descriptor = yaml.safe_load((root / "services.yaml").read_text())
    field = descriptor[SERVICE_RESET]["fields"]["entity_id"]
    assert field["required"] is True
    assert field["selector"]["entity"]["multiple"] is False
    translations = [
        json.loads((root / "translations" / f"{language}.json").read_text())
        for language in ("en", "fr")
    ]
    assert translations[0]["exceptions"].keys() == translations[1]["exceptions"].keys()
    for translation in translations:
        service = translation["services"][SERVICE_RESET]
        assert service["name"]
        assert service["description"]
        assert service["fields"]["entity_id"]["name"]
        assert all(error["message"] for error in translation["exceptions"].values())