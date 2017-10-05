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

import mock

from networking_generic_switch.devices.netmiko_devices import juniper
from networking_generic_switch.tests.unit.netmiko import test_netmiko_base


class TestNetmikoJuniper(test_netmiko_base.NetmikoSwitchTestBase):

    def _make_switch_device(self, extra_cfg={}):
        device_cfg = {'device_type': 'netmiko_juniper'}
        device_cfg.update(extra_cfg)
        return juniper.Juniper(device_cfg)

    def test_constants(self):
        self.assertIsNone(self.switch.SAVE_CONFIGURATION)

    @mock.patch('networking_generic_switch.devices.netmiko_devices.'
                'NetmikoSwitch.send_commands_to_device')
    def test_add_network(self, m_exec):
        self.switch.add_network(33, '0ae071f5-5be9-43e4-80ea-e41fefe85b21')
        m_exec.assert_called_with(
            ['set vlans 0ae071f55be943e480eae41fefe85b21 vlan-id 33'])

    @mock.patch('networking_generic_switch.devices.netmiko_devices.'
                'NetmikoSwitch.send_commands_to_device')
    def test_add_network_with_trunk_ports(self, mock_exec):
        switch = self._make_switch_device({'ngs_trunk_ports': 'port1,port2'})
        switch.add_network(33, '0ae071f5-5be9-43e4-80ea-e41fefe85b21')
        mock_exec.assert_called_with(
            ['set vlans 0ae071f55be943e480eae41fefe85b21 vlan-id 33',
             'set interface port1 unit 0 family ethernet-switching '
             'vlan members 33',
             'set interface port2 unit 0 family ethernet-switching '
             'vlan members 33'])

    @mock.patch('networking_generic_switch.devices.netmiko_devices.'
                'NetmikoSwitch.send_commands_to_device')
    def test_del_network(self, mock_exec):
        self.switch.del_network(33, '0ae071f55be943e480eae41fefe85b21')
        mock_exec.assert_called_with([
            'delete vlans 0ae071f55be943e480eae41fefe85b21'])

    @mock.patch('networking_generic_switch.devices.netmiko_devices.'
                'NetmikoSwitch.send_commands_to_device')
    def test_del_network_with_trunk_ports(self, mock_exec):
        switch = self._make_switch_device({'ngs_trunk_ports': 'port1,port2'})
        switch.del_network(33, '0ae071f55be943e480eae41fefe85b21')
        mock_exec.assert_called_with(
            ['delete interface port1 unit 0 family ethernet-switching '
             'vlan members 33',
             'delete interface port2 unit 0 family ethernet-switching '
             'vlan members 33',
             'delete vlans 0ae071f55be943e480eae41fefe85b21'])

    @mock.patch('networking_generic_switch.devices.netmiko_devices.'
                'NetmikoSwitch.send_commands_to_device')
    def test_plug_port_to_network(self, mock_exec):
        self.switch.plug_port_to_network(3333, 33)
        mock_exec.assert_called_with(
            ['delete interface 3333 unit 0 family ethernet-switching '
             'vlan members',
             'set interface 3333 unit 0 family ethernet-switching '
             'vlan members 33'])

    @mock.patch('networking_generic_switch.devices.netmiko_devices.'
                'NetmikoSwitch.send_commands_to_device')
    def test_delete_port(self, mock_exec):
        self.switch.delete_port(3333, 33)
        mock_exec.assert_called_with(
            ['delete interface 3333 unit 0 family ethernet-switching '
             'vlan members'])

    def test_save_configuration(self):
        mock_connection = mock.Mock()
        self.switch.save_configuration(mock_connection)
        mock_connection.commit.assert_called_once_with()

    def test__format_commands(self):
        cmd_set = self.switch._format_commands(
            juniper.Juniper.ADD_NETWORK,
            segmentation_id=22,
            network_id=22)
        self.assertEqual(cmd_set, ['set vlans 22 vlan-id 22'])

        cmd_set = self.switch._format_commands(
            juniper.Juniper.DELETE_NETWORK,
            segmentation_id=22,
            network_id=22)
        self.assertEqual(cmd_set, ['delete vlans 22'])

        cmd_set = self.switch._format_commands(
            juniper.Juniper.PLUG_PORT_TO_NETWORK,
            port=3333,
            segmentation_id=33)
        self.assertEqual(cmd_set,
                         ['delete interface 3333 unit 0 '
                          'family ethernet-switching '
                          'vlan members',
                          'set interface 3333 unit 0 '
                          'family ethernet-switching '
                          'vlan members 33'])

        cmd_set = self.switch._format_commands(
            juniper.Juniper.DELETE_PORT,
            port=3333,
            segmentation_id=33)
        self.assertEqual(cmd_set,
                         ['delete interface 3333 unit 0 '
                          'family ethernet-switching '
                          'vlan members'])

        cmd_set = self.switch._format_commands(
            juniper.Juniper.PLUG_TRUNK_PORT_TO_NETWORK,
            port=3333,
            segmentation_id=33)
        self.assertEqual(cmd_set,
                         ['set interface 3333 unit 0 '
                          'family ethernet-switching '
                          'vlan members 33'])

        cmd_set = self.switch._format_commands(
            juniper.Juniper.UNPLUG_TRUNK_PORT_FROM_NETWORK,
            port=3333,
            segmentation_id=33)
        self.assertEqual(cmd_set,
                         ['delete interface 3333 unit 0 '
                          'family ethernet-switching '
                          'vlan members 33'])
