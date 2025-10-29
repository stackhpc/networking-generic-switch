# Copyright 2016 Mirantis, Inc.
#
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

import re

from networking_generic_switch.devices import netmiko_devices
from networking_generic_switch import exceptions as exc


class DellOS10(netmiko_devices.NetmikoSwitch):
    """Netmiko device driver for Dell PowerSwitch switches."""

    ADD_NETWORK = (
        "interface vlan {segmentation_id}",
        "description {network_name}",
        "exit",
    )

    DELETE_NETWORK = (
        "no interface vlan {segmentation_id}",
        "exit",
    )

    PLUG_PORT_TO_NETWORK = (
        "interface {port}",
        "switchport mode access",
        "switchport access vlan {segmentation_id}",
        "exit",
    )

    DELETE_PORT = (
        "interface {port}",
        "no switchport access vlan",
        "exit",
    )

    ADD_NETWORK_TO_TRUNK = (
        "interface {port}",
        "switchport mode trunk",
        "switchport trunk allowed vlan {segmentation_id}",
        "exit",
    )

    REMOVE_NETWORK_FROM_TRUNK = (
        "interface {port}",
        "no switchport trunk allowed vlan {segmentation_id}",
        "exit",
    )

    ENABLE_PORT = (
        "interface {port}",
        "no shutdown",
        "exit",
    )

    DISABLE_PORT = (
        "interface {port}",
        "shutdown",
        "exit",
    )

    SET_NATIVE_VLAN = (
        'interface {port}',
        # Clean all the old trunked vlans by switching to access mode first
        'switchport mode access',
        'switchport mode trunk',
        'switchport access vlan {segmentation_id}',
    )

    ALLOW_NETWORK_ON_TRUNK = (
        'interface {port}',
        'switchport trunk allowed vlan {segmentation_id}'
    )

    ERROR_MSG_PATTERNS = ()
    """Sequence of error message patterns.

    Sequence of re.RegexObject objects representing patterns to check for in
    device output that indicate a failure to apply configuration.
    """


class DellNos(netmiko_devices.NetmikoSwitch):
    """Netmiko device driver for Dell Force10 (OS9) switches."""

    ADD_NETWORK = (
        'interface vlan {segmentation_id}',
        # It's not possible to set the name on OS9: the field takes 32
        # chars max, and cannot begin with a number. Let's set the
        # description and leave the name empty.
        'description {network_name}',
        'exit',
    )

    DELETE_NETWORK = (
        'no interface vlan {segmentation_id}',
        'exit',
    )

    PLUG_PORT_TO_NETWORK = (
        'interface vlan {segmentation_id}',
        'untagged {port}',
        'exit',
    )

    DELETE_PORT = (
        'interface vlan {segmentation_id}',
        'no untagged {port}',
        'exit',
    )

    ADD_NETWORK_TO_TRUNK = (
        'interface vlan {segmentation_id}',
        'tagged {port}',
        'exit',
    )

    REMOVE_NETWORK_FROM_TRUNK = (
        'interface vlan {segmentation_id}',
        'no tagged {port}',
        'exit',
    )


class DellEnterpriseSonicCli(netmiko_devices.NetmikoSwitch):
    """Netmiko device driver for Dell Enterprise switches.

       Developed against SONiC-OS-4.2.3-Edge_Standard.

       This driver uses the sonic-cli rather than Linux userspace to
       configure the switch. This is because LLDP advertises switch
       ports based on the naming from the sonic-cli, which is not the
       same as Linux userspace.
    """

    NETMIKO_DEVICE_TYPE = "dell_sonic_ssh"

    ADD_NETWORK = (
        'interface Vlan {segmentation_id}',
    )

    DELETE_NETWORK = (
        'no interface Vlan {segmentation_id}',
    )

    PLUG_PORT_TO_NETWORK = (
        'interface {port}',
        'switchport access Vlan {segmentation_id}',
    )

    DELETE_PORT = (
        'interface {port}',
        'no switchport access Vlan',
    )

    SAVE_CONFIGURATION = (
        'copy running-configuration startup-configuration',
    )

    # TODO(dougszu): We need some typical failures to add here
    ERROR_MSG_PATTERNS = []

    def save_configuration(self, net_connect):
        """Try to save the device's configuration.

        :param net_connect: a netmiko connection object.
        """
        # NOTE(dougszu): We override this because the default
        # method tries 'copy running-config startup-config' which
        # is transformed by the switch to:
        # 'copy running-configuration startup-configuration'.
        for cmd in self.SAVE_CONFIGURATION:
            net_connect.send_command(cmd)

    def send_config_set(self, net_connect, cmd_set):
        """Send a set of configuration lines to the device.

        :param net_connect: a netmiko connection object.
        :param cmd_set: a list of configuration lines to send.
        :returns: The output of the configuration commands.
        """
        net_connect.enable()
        # NOTE(dougszu): We override this so that we wait for commands
        # to run before moving on.
        return net_connect.send_config_set(config_commands=cmd_set,
                                           cmd_verify=True)


class DellPowerConnect(netmiko_devices.NetmikoSwitch):
    """Netmiko device driver for Dell PowerConnect switches."""

    def _switch_to_general_mode(self):
        self.PLUG_PORT_TO_NETWORK = self.PLUG_PORT_TO_NETWORK_GENERAL
        self.DELETE_PORT = self.DELETE_PORT_GENERAL

    def __init__(self, device_cfg, *args, **kwargs):
        super(DellPowerConnect, self).__init__(device_cfg, *args, **kwargs)
        port_mode = self.ngs_config['ngs_switchport_mode']
        switchport_mode = {
            'general': self._switch_to_general_mode,
            'access': lambda: ()
        }

        def on_invalid_switchmode():
            raise exc.GenericSwitchConfigException(
                option="ngs_switchport_mode",
                allowed_options=switchport_mode.keys()
            )

        switchport_mode.get(port_mode.lower(), on_invalid_switchmode)()

    ADD_NETWORK = (
        'vlan database',
        'vlan {segmentation_id}',
        'exit',
    )

    DELETE_NETWORK = (
        'vlan database',
        'no vlan {segmentation_id}',
        'exit',
    )

    PLUG_PORT_TO_NETWORK_GENERAL = (
        'interface {port}',
        'switchport general allowed vlan add {segmentation_id} untagged',
        'switchport general pvid {segmentation_id}',
        'exit',
    )

    PLUG_PORT_TO_NETWORK = (
        'interface {port}',
        'switchport access vlan {segmentation_id}',
        'exit',
    )

    DELETE_PORT_GENERAL = (
        'interface {port}',
        'switchport general allowed vlan remove {segmentation_id}',
        'no switchport general pvid',
        'exit',
    )

    DELETE_PORT = (
        'interface {port}',
        'switchport access vlan none',
        'exit',
    )

    ADD_NETWORK_TO_TRUNK = (
        'interface {port}',
        'switchport general allowed vlan add {segmentation_id} tagged',
        'exit',
    )

    REMOVE_NETWORK_FROM_TRUNK = (
        'interface {port}',
        'switchport general allowed vlan remove {segmentation_id}',
        'exit',
    )

    ERROR_MSG_PATTERNS = (
        re.compile(r'\% Incomplete command'),
        re.compile(r'VLAN was not created by user'),
        re.compile(r'Configuration Database locked by another application \- '
                   r'try later'),
    )
