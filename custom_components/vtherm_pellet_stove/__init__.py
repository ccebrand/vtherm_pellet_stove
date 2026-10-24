"""The vtherm_pellet_stove integration."""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol
from homeassistant.auth.permissions.const import POLICY_CONTROL
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    Platform,
)
from homeassistant.core import CoreState, HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError, Unauthorized, UnknownUser
from homeassistant.helpers import config_validation as cv, entity_registry as er
from vtherm_api.log_collector import get_vtherm_logger
from vtherm_api.vtherm_api import VThermAPI

from .const import (
    CONF_PROP_FUNCTION,
    CONF_TARGET_VTHERM,
    DATA_FACTORY_REGISTERED,
    DATA_HANDLERS,
    DATA_LOADED_ENTRIES,
    DOMAIN,
    PROP_FUNCTION_PELLET_REGULATION,
    SERVICE_RESET,
)
from .factory import PelletRegulationFactory

VT_DOMAIN = "versatile_thermostat"

#: Plateforme sensor pour l'entité de débogage.
#: Activée uniquement sur l'entrée globale (unique_id == DOMAIN).
_PLATFORMS = [Platform.SENSOR]

_LOGGER = get_vtherm_logger(__name__)


def _ensure_domain_data(hass: HomeAssistant) -> dict[str, Any]:
    """Return the plugin data storage in hass."""
    return hass.data.setdefault(DOMAIN, {})


def _register_services(hass: HomeAssistant) -> None:
    """Register reset once for all active pellet thermostats."""
    if hass.services.has_service(DOMAIN, SERVICE_RESET):
        return

    async def async_reset(call: ServiceCall) -> None:
        entity_id = call.data[ATTR_ENTITY_ID]
        if call.context.user_id:
            user = await hass.auth.async_get_user(call.context.user_id)
            if user is None:
                raise UnknownUser(context=call.context)
            if not user.permissions.check_entity(entity_id, POLICY_CONTROL):
                raise Unauthorized(context=call.context, entity_id=entity_id)

        entry = er.async_get(hass).async_get(entity_id)
        handlers = _ensure_domain_data(hass).get(DATA_HANDLERS, {})
        handler = handlers.get(entry.unique_id) if entry is not None else None
        state = hass.states.get(entity_id)
        if (
            entry is None
            or entry.platform != VT_DOMAIN
            or not entity_id.startswith("climate.")
            or handler is None
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_reset_target"
            )
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="reset_target_unavailable"
            )
        await handler.async_reset(call.context)

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET,
        async_reset,
        schema=vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_id}),
    )


def _register_factory(hass: HomeAssistant) -> bool:
    """Register the PelletRegulation factory in the shared VT API."""
    data = _ensure_domain_data(hass)
    if data.get(DATA_FACTORY_REGISTERED) is True:
        return True

    api = VThermAPI.get_vtherm_api(hass)
    if api is None:
        _LOGGER.warning(
            "Unable to register PelletRegulation factory because VThermAPI is unavailable"
        )
        return False

    factory = PelletRegulationFactory()
    existing = api.get_prop_algorithm(factory.name)
    if existing is None:
        api.register_prop_algorithm(factory)

    data[DATA_FACTORY_REGISTERED] = True
    return True


def _unregister_factory(hass: HomeAssistant) -> None:
    """Unregister the PelletRegulation factory from the shared VT API."""
    api = VThermAPI.get_vtherm_api(hass)
    if api is not None:
        api.unregister_prop_algorithm(PROP_FUNCTION_PELLET_REGULATION)
    _ensure_domain_data(hass)[DATA_FACTORY_REGISTERED] = False


async def _reload_pellet_vtherms(
    hass: HomeAssistant,
    source_entry: ConfigEntry | None = None,
) -> None:
    """Reload VT entries that currently use the pellet_regulation proportional function."""
    target_unique_id: str | None = None
    reload_global_defaults = False

    if source_entry is not None:
        target_unique_id = source_entry.data.get(CONF_TARGET_VTHERM)
        reload_global_defaults = target_unique_id is None

    # Collect all VTherm unique IDs that have a per-thermostat entry in this plugin.
    per_thermostat_targets = {
        entry.data.get(CONF_TARGET_VTHERM)
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get(CONF_TARGET_VTHERM)
    }

    reload_tasks = []
    reloaded_entry_ids: list[str] = []
    for entry in hass.config_entries.async_entries(VT_DOMAIN):
        if entry.data.get(CONF_PROP_FUNCTION) != PROP_FUNCTION_PELLET_REGULATION:
            continue

        if target_unique_id is not None:
            # Per-thermostat entry changed: reload only the matching VTherm.
            if entry.unique_id != target_unique_id:
                continue
        elif reload_global_defaults and entry.unique_id in per_thermostat_targets:
            # Global defaults changed: skip VTherms that have an override entry.
            continue

        reloaded_entry_ids.append(entry.entry_id)
        reload_tasks.append(hass.config_entries.async_reload(entry.entry_id))

    if reload_tasks:
        await asyncio.gather(*reload_tasks)

        # VT's reload may destroy and recreate the VThermAPI instance (when the
        # last VT config entry is removed by remove_entry).  The new API starts
        # with an empty algorithm registry, so our factory is lost.
        #
        # Fix: re-register the factory on the (possibly new) API, then retry
        # init_vtherm_links for each reloaded entry so that any entity that
        # previously raised "Unknown proportional function" gets a second chance.
        data = _ensure_domain_data(hass)
        data.pop(DATA_FACTORY_REGISTERED, None)
        if _register_factory(hass):
            api = VThermAPI.get_vtherm_api(hass)
            if api is not None and hasattr(api, "init_vtherm_links"):
                for entry_id in reloaded_entry_ids:
                    try:
                        await api.init_vtherm_links(entry_id)
                    except Exception as exc:  # pylint: disable=broad-except
                        _LOGGER.warning(
                            "Could not re-initialize VTherm entry %s after reload: %s",
                            entry_id,
                            exc,
                        )


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up vtherm_pellet_stove from YAML."""
    del config
    _register_factory(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up vtherm_pellet_stove from a config entry."""
    data = _ensure_domain_data(hass)
    _register_factory(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    # La plateforme sensor n'est activée que pour l'entrée globale afin
    # d'avoir un unique callback async_add_entities partagé par tous les handlers.
    if entry.unique_id == DOMAIN:
        await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    data[entry.entry_id] = entry.entry_id
    data.setdefault(DATA_LOADED_ENTRIES, set()).add(entry.entry_id)
    _register_services(hass)
    return True


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options change so new params are picked up.

    Reloading the entry is the standard HA pattern: ``async_setup_entry`` then
    calls ``_reload_pellet_vtherms`` which re-initialises all affected VTherm
    handlers with the freshly-saved options.
    """

    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a vtherm_pellet_stove config entry."""
    data = _ensure_domain_data(hass)

    # Décharger la plateforme sensor de l'entrée globale si applicable.
    if entry.unique_id == DOMAIN:
        if not await hass.config_entries.async_unload_platforms(entry, _PLATFORMS):
            return False
        # Nettoyer le callback stocké.
        from .const import DATA_SENSOR_ADD_CB  # pylint: disable=import-outside-toplevel

        data.pop(DATA_SENSOR_ADD_CB, None)

    data.pop(entry.entry_id, None)
    loaded_entries = data.setdefault(DATA_LOADED_ENTRIES, set())
    loaded_entries.discard(entry.entry_id)

    # Unregister the factory only when the last plugin entry is removed.
    # When it IS the last entry, also reload the VTherm thermostats so they
    # detect that pellet_regulation is no longer available.  During a normal
    # entry reload (triggered by an options update) other plugin entries are
    # still present, so the factory stays registered and no VTherm reload is
    # needed here — async_setup_entry will handle it.
    if not loaded_entries:
        hass.services.async_remove(DOMAIN, SERVICE_RESET)
        _unregister_factory(hass)
        await _reload_pellet_vtherms(hass)

    return True
