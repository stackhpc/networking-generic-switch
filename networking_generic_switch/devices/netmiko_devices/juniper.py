# Copyright (c) 2017 StackHPC Ltd.
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

from networking_generic_switch.devices import netmiko_devices


class Juniper(netmiko_devices.NetmikoSwitch):

    ADD_NETWORK = (
        'set vlans {network_id} vlan-id {segmentation_id}',
    )

    DELETE_NETWORK = (
        'delete vlans {network_id}',
    )

    PLUG_PORT_TO_NETWORK = (
        # Delete any existing VLAN associations - only one VLAN may be
        # associated with an access mode port.
        'delete interface {port} unit 0 family ethernet-switching '
        'vlan members',
        'set interface {port} unit 0 family ethernet-switching '
        'vlan members {segmentation_id}',
    )

    DELETE_PORT = (
        'delete interface {port} unit 0 family ethernet-switching '
        'vlan members',
    )

    PLUG_TRUNK_PORT_TO_NETWORK = (
        'set interface {port} unit 0 family ethernet-switching '
        'vlan members {segmentation_id}',
    )

    UNPLUG_TRUNK_PORT_FROM_NETWORK = (
        'delete interface {port} unit 0 family ethernet-switching '
        'vlan members {segmentation_id}',
    )

    def save_configuration(self, net_connect):
        """Save the device's configuration.

        :param net_connect: a netmiko connection object.
        """
        # Junos configuration is transactional, and requires an explicit commit
        # of changes in order for them to be applied.
        net_connect.commit()
