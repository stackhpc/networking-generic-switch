#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import contextlib
import random
import re

from oslo_log import log as logging

from networking_generic_switch.devices import netmiko_devices
from networking_generic_switch import exceptions as exc


LOG = logging.getLogger(__name__)

RANDOM_FAILURE_PROB = 0
"""Probability of injecting a failure event."""


class DummyConnection(object):
    def enable(self):
        pass

    def send_config_set(self, config_commands, cmd_verify):
        if random.random() < RANDOM_FAILURE_PROB:
            raise Exception("Random failure!")
        for cmd in config_commands:
            LOG.info("%s", cmd)
        return "Success!"

    def save_config(self):
        pass

    def send_command(self, command):
        LOG.info("%s", command)
        return "Success!"


class Dummy(netmiko_devices.NetmikoSwitch):
    """Netmiko device driver for Dummy switches."""

    NETMIKO_DEVICE_TYPE = "linux"

    ADD_NETWORK = (
        "add network {segmentation_id}",
    )

    DELETE_NETWORK = (
        "delete network {segmentation_id}",
    )

    PLUG_PORT_TO_NETWORK = (
        "plug port {port} to network {segmentation_id}",
    )

    DELETE_PORT = (
        "delete port {port}",
    )

    ADD_NETWORK_TO_TRUNK = (
        "add network {segmentation_id} to trunk {port}",
    )

    REMOVE_NETWORK_FROM_TRUNK = (
        "remove network {segmentation_id} from trunk {port}",
    )

    ENABLE_PORT = (
        "enable {port}",
    )

    DISABLE_PORT = (
        "disable {port}",
    )

    ERROR_MSG_PATTERNS = ()
    """Sequence of error message patterns.

    Sequence of re.RegexObject objects representing patterns to check for in
    device output that indicate a failure to apply configuration.
    """

    @contextlib.contextmanager
    def _get_connection(self):
        """Context manager providing a netmiko SSH connection object.

        This function hides the complexities of gracefully handling retrying
        failed connection attempts.
        """
        yield DummyConnection()
