# Copyright 2026 StackHPC
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


class AlliedWarePlus(netmiko_devices.NetmikoSwitch):
    """Device Name: AlliedWare Plus

    Port can be disabled: True
    """

    ADD_NETWORK = (
        "vlan database",
        "vlan {segmentation_id} state enable",
        "exit",
    )

    DELETE_NETWORK = (
        "vlan database",
        "no vlan {segmentation_id}",
        "exit",
    )

    PLUG_PORT_TO_NETWORK = (
        "interface {port}",
        "switchport mode access",
        "switchport access vlan {segmentation_id}",
        "exit",
    )

    PLUG_BOND_TO_NETWORK = (
        "interface {bond}",
        "switchport mode access",
        "switchport access vlan {segmentation_id}",
        "exit",
    )

    DELETE_PORT = (
        "interface {port}",
        "no switchport access vlan",
        "exit",
    )

    UNPLUG_BOND_FROM_NETWORK = (
        "interface {bond}",
        "no switchport access vlan",
        "exit",
    )

    ADD_NETWORK_TO_TRUNK = (
        "interface {port}",
        "switchport mode trunk",
        "switchport trunk allowed vlan add {segmentation_id}",
        "exit",
    )

    ADD_NETWORK_TO_BOND_TRUNK = (
        "interface {bond}",
        "switchport mode trunk",
        "switchport trunk allowed vlan add {segmentation_id}",
        "exit",
    )

    REMOVE_NETWORK_FROM_TRUNK = (
        "interface {port}",
        "switchport trunk allowed vlan remove {segmentation_id}",
        "exit",
    )

    DELETE_NETWORK_ON_BOND_TRUNK = (
        "interface {bond}",
        "switchport trunk allowed vlan remove {segmentation_id}",
        "exit",
    )

    SET_NATIVE_VLAN = (
        'interface {port}',
        'switchport mode trunk',
        'switchport trunk native vlan {segmentation_id}',
        "exit",
    )

    SET_NATIVE_VLAN_BOND = (
        'interface {bond}',
        'switchport mode trunk',
        'switchport trunk native vlan {segmentation_id}',
        "exit",
    )

    DELETE_NATIVE_VLAN = (
        'interface {port}',
        'no switchport trunk native vlan',
        "exit",
    )

    DELETE_NATIVE_VLAN_BOND = (
        'interface {bond}',
        'no switchport trunk native vlan',
        "exit",
    )

    SET_PORT_MTU = (
        "interface {port}",
        "mru {mtu}",
        "exit",
    )

    SET_PORT_STP_EDGE = (
        "interface {port}",
        "spanning-tree edgeport",
        "exit",
    )

    UNSET_PORT_STP_EDGE = (
        "interface {port}",
        "no spanning-tree edgeport",
        "exit",
    )

    SET_PORT_BPDU_GUARD = (
        "interface {port}",
        "spanning-tree portfast bpdu-guard enable",
        "exit",
    )

    UNSET_PORT_BPDU_GUARD = (
        "interface {port}",
        "spanning-tree portfast bpdu-guard disable",
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

    ERROR_MSG_PATTERNS = (
        re.compile(r'^\%'),
    )
