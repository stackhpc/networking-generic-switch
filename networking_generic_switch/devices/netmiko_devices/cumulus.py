# Copyright 2020 StackHPC
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


class Cumulus(netmiko_devices.NetmikoSwitch):
    ADD_NETWORK = (
    )

    DELETE_NETWORK = (
    )

    PLUG_PORT_TO_NETWORK = (
        'net del interface {port}',
        'net commit',
        'net add interface {port} bridge access {segmentation_id}',
        'net del interface {port} link down',
        'net commit',
    )

    DELETE_PORT = (
        'net del interface {port}',
        'net interface {port} link down',
        'net commit'
    )
