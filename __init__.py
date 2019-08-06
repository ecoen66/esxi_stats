"""ESXi Stats Integration."""

import atexit
import logging
import os
from datetime import timedelta, datetime, date
from .esxi import get_content, get_host_info, get_datastore_info, get_vm_info

import homeassistant.helpers.config_validation as cv
from homeassistant.const import (
    CONF_HOST,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_VERIFY_SSL,
    CONF_MONITORED_CONDITIONS,
)
from homeassistant.helpers import discovery
from homeassistant.util import Throttle

import voluptuous as vol

from pyVmomi import vim  # pylint: disable=no-name-in-module

from .const import (
    CONF_NAME,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DOMAIN,
    DOMAIN_DATA,
    ISSUE_URL,
    PLATFORMS,
    REQUIRED_FILES,
    STARTUP,
    VERSION,
)

_LOGGER = logging.getLogger(__name__)
MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=60)

MONITORED_CONDITIONS = {
    "hosts": ["ESXi Host", "", ""],
    "vms": ["Virtual Machines", "", ""],
    "datastores": ["Datastores", "", ""],
}

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_HOST): cv.string,
                vol.Required(CONF_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.positive_int,
                vol.Optional(CONF_VERIFY_SSL, default=False): cv.boolean,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
                vol.Optional("scan_interval", default=60): cv.positive_int,
                vol.Optional(CONF_MONITORED_CONDITIONS, default=["hosts"]): vol.All(
                    cv.ensure_list, [vol.In(MONITORED_CONDITIONS)]
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass, config):
    # startup message
    startup = STARTUP.format(name=DOMAIN, version=VERSION, issueurl=ISSUE_URL)
    _LOGGER.info(startup)

    # check all required files
    file_check = await check_files(hass)
    if not file_check:
        return False

    # create data dictionary
    hass.data[DOMAIN_DATA] = {}
    hass.data[DOMAIN_DATA]["hosts"] = {}
    hass.data[DOMAIN_DATA]["datastores"] = {}
    hass.data[DOMAIN_DATA]["vms"] = {}
    hass.data[DOMAIN_DATA]["monitored_conditions"] = config[DOMAIN].get(
        CONF_MONITORED_CONDITIONS
    )

    # get global config
    _LOGGER.debug("Setting up host %s", config[DOMAIN].get(CONF_HOST))
    hass.data[DOMAIN_DATA]["client"] = esxiStats(hass, config)

    # load platforms
    for platform in PLATFORMS:
        # Get platform specific configuration
        platform_config = config[DOMAIN]

        hass.async_create_task(
            discovery.async_load_platform(
                hass, platform, DOMAIN, platform_config, config
            )
        )

    return True


class esxiStats:
    def __init__(self, hass, config):
        """Initialize the class."""
        self.hass = hass
        self.host = config[DOMAIN].get(CONF_HOST)
        self.user = config[DOMAIN].get(CONF_USERNAME)
        self.passwd = config[DOMAIN].get(CONF_PASSWORD)
        self.port = config[DOMAIN].get(CONF_PORT)
        self.ssl = config[DOMAIN].get(CONF_VERIFY_SSL)
        self.monitored_conditions = config[DOMAIN].get(CONF_MONITORED_CONDITIONS)

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    async def update_data(self):
        try:
            # get data from host
            content = get_content(
                self.host, self.user, self.passwd, self.port, self.ssl
            )

            # create/distroy view objects
            host_objview = content.viewManager.CreateContainerView(
                content.rootFolder, [vim.HostSystem], True
            )
            ds_objview = content.viewManager.CreateContainerView(
                content.rootFolder, [vim.Datastore], True
            )
            vm_objview = content.viewManager.CreateContainerView(
                content.rootFolder, [vim.VirtualMachine], True
            )

            esxi_hosts = host_objview.view
            ds_list = ds_objview.view
            vm_list = vm_objview.view

            host_objview.Destroy()
            ds_objview.Destroy()
            vm_objview.Destroy()

            # get host stats
            if "hosts" in self.monitored_conditions:
                for esxi_host in esxi_hosts:
                    host_name = esxi_host.summary.config.name.replace(" ", "_").lower()

                    self.hass.data[DOMAIN_DATA]["hosts"][host_name] = get_host_info(
                        esxi_host
                    )
                    _LOGGER.debug("Getting stats for host: %s", host_name)

            # get datastore stats
            if "datastores" in self.monitored_conditions:
                for ds in ds_list:
                    ds_name = ds.summary.name.replace(" ", "_").lower()

                    self.hass.data[DOMAIN_DATA]["datastores"][
                        ds_name
                    ] = get_datastore_info(ds)
                    _LOGGER.debug("Getting stats for datastore: %s", ds_name)

            # get vm stats
            if "vms" in self.monitored_conditions:
                for vm in vm_list:
                    vm_name = vm.summary.config.name.replace(" ", "_").lower()

                    self.hass.data[DOMAIN_DATA]["vms"][vm_name] = get_vm_info(vm)
                    _LOGGER.debug("Getting stats for vm: %s", vm_name)

            # print(self.hass.data[DOMAIN_DATA]["datastores"])
        except Exception as error:
            _LOGGER.error("ERROR: %s", error)


async def check_files(hass):
    """Return bool that indicates if all files are present."""
    base = "{}/custom_components/{}/".format(hass.config.path(), DOMAIN)
    missing = []
    for file in REQUIRED_FILES:
        fullpath = "{}{}".format(base, file)
        if not os.path.exists(fullpath):
            missing.append(file)

    if missing:
        _LOGGER.critical("The following files are missing: %s", str(missing))
        returnvalue = False
    else:
        returnvalue = True

    return returnvalue
