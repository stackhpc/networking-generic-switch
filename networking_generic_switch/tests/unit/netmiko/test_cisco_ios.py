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

from unittest import mock

from neutron.plugins.ml2 import driver_context

from networking_generic_switch.devices.netmiko_devices import cisco
from networking_generic_switch.tests.unit.netmiko import test_netmiko_base


class TestNetmikoCiscoIos(test_netmiko_base.NetmikoSwitchTestBase):

    def _make_switch_device(self):
        device_cfg = {'device_type': 'netmiko_cisco_ios'}
        return cisco.CiscoIos(device_cfg)

    def test_constants(self):
        self.assertIsNone(self.switch.SAVE_CONFIGURATION)

    @mock.patch('networking_generic_switch.devices.netmiko_devices.'
                'NetmikoSwitch.send_commands_to_device', autospec=True)
    def test_add_network(self, m_exec):
        self.switch.add_network(33, '0ae071f5-5be9-43e4-80ea-e41fefe85b21')
        m_exec.assert_called_with(
            self.switch,
            ['vlan 33', 'name 0ae071f55be943e480eae41fefe85b21'])

    @mock.patch('networking_generic_switch.devices.netmiko_devices.'
                'NetmikoSwitch.send_commands_to_device', autospec=True)
    def test_del_network(self, mock_exec):
        self.switch.del_network(33, '0ae071f5-5be9-43e4-80ea-e41fefe85b21')
        mock_exec.assert_called_with(self. switch, ['no vlan 33'])

    @mock.patch('networking_generic_switch.devices.netmiko_devices.'
                'NetmikoSwitch.send_commands_to_device', autospec=True)
    def test_plug_port_to_network(self, mock_exec):
        self.switch.plug_port_to_network(3333, 33)
        mock_exec.assert_called_with(
            self.switch,
            ['interface 3333', 'switchport mode access',
             'switchport access vlan 33'])

    @mock.patch('networking_generic_switch.devices.netmiko_devices.'
                'NetmikoSwitch.send_commands_to_device', autospec=True)
    def test_delete_port(self, mock_exec):
        self.switch.delete_port(3333, 33)
        mock_exec.assert_called_with(
            self.switch,
            ['interface 3333', 'no switchport access vlan 33',
             'no switchport mode trunk', 'switchport trunk allowed vlan none'])

    def test_get_trunk_port_cmds_no_vlan_translation(self):
        mock_context = mock.create_autospec(driver_context.PortContext)
        self.switch.ngs_config['vlan_translation_supported'] = True
        trunk_details = {'trunk_id': 'aaa-bbb-ccc-ddd',
                         'sub_ports': [{'segmentation_id': 130,
                                        'port_id': 'aaa-bbb-ccc-ddd',
                                        'segmentation_type': 'vlan',
                                        'mac_address': u'fa:16:3e:1c:c2:7e'}]}
        mock_context.current = {'binding:profile':
                                {'local_link_information':
                                    [
                                        {
                                            'switch_info': 'foo',
                                            'port_id': '2222'
                                        }
                                    ]
                                 },
                                'binding:vnic_type': 'baremetal',
                                'id': 'aaaa-bbbb-cccc',
                                'trunk_details': trunk_details}
        mock_context.network = mock.Mock()
        mock_context.network.current = {'provider:segmentation_id': 123}
        mock_context.segments_to_bind = [
            {
                'segmentation_id': 777,
                'id': 123
            }
        ]
        res = self.switch.get_trunk_port_cmds_no_vlan_translation(
            '2222', 777, trunk_details)
        self.assertEqual(['interface 2222', 'switchport mode trunk',
                          'switchport trunk native vlan 777',
                          'switchport trunk allowed vlan add 777',
                          'interface 2222',
                          'switchport trunk allowed vlan add 130'],
                         res)

    def test__format_commands(self):
        cmd_set = self.switch._format_commands(
            cisco.CiscoIos.ADD_NETWORK,
            segmentation_id=22,
            network_id=22,
            network_name='vlan-22')
        self.assertEqual(cmd_set, ['vlan 22', 'name vlan-22'])

        cmd_set = self.switch._format_commands(
            cisco.CiscoIos.DELETE_NETWORK,
            segmentation_id=22)
        self.assertEqual(cmd_set, ['no vlan 22'])

        cmd_set = self.switch._format_commands(
            cisco.CiscoIos.PLUG_PORT_TO_NETWORK,
            port=3333,
            segmentation_id=33)
        plug_exp = ['interface 3333', 'switchport mode access',
                    'switchport access vlan 33']
        self.assertEqual(plug_exp, cmd_set)

        cmd_set = self.switch._format_commands(
            cisco.CiscoIos.DELETE_PORT,
            port=3333,
            segmentation_id=33)
        del_exp = ['interface 3333',
                   'no switchport access vlan 33',
                   'no switchport mode trunk',
                   'switchport trunk allowed vlan none']
        self.assertEqual(del_exp, cmd_set)
