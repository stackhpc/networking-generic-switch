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

from unittest import mock

import fixtures
from oslo_config import fixture as config_fixture
from oslo_utils import uuidutils
import tenacity

from networking_generic_switch import batching


class SwitchQueueTest(fixtures.TestWithFixtures):
    def setUp(self):
        super(SwitchQueueTest, self).setUp()
        self.cfg = self.useFixture(config_fixture.Config())

        self.client = mock.Mock()
        self.switch_name = "switch1"
        self.queue = batching.SwitchQueue(self.switch_name, self.client)

    @mock.patch.object(uuidutils, "generate_uuid")
    @mock.patch.object(batching.SwitchQueue, "_watch_for_result")
    def test_add_batch_and_wait_for_result(self, mock_watch, mock_uuid):
        mock_watch.return_value = ("watcher", "callback")
        mock_uuid.return_value = "uuid"

        callback = self.queue.add_batch_and_wait_for_result(["cmd1", "cmd2"])

        self.assertEqual("callback", callback)
        mock_watch.assert_called_once_with('/ngs/batch/switch1/output/uuid')
        self.client.create.assert_called_once_with(
            '/ngs/batch/switch1/input/uuid',
            b'{"cmds": ["cmd1", "cmd2"], '
            b'"input_key": "/ngs/batch/switch1/input/uuid", '
            b'"result_key": "/ngs/batch/switch1/output/uuid", '
            b'"uuid": "uuid"}'
        )

    def test_get_and_delete_result(self):
        self.client.get.return_value = [b'{"foo": "bar"}']

        result = self.queue._get_and_delete_result("result_key")

        self.assertEqual({"foo": "bar"}, result)
        self.client.get.assert_called_once_with("result_key")
        self.client.delete.assert_called_once_with("result_key")

    def test_get_batches(self):
        self.client.get_prefix.return_value = [
            (b'{"foo": "bar"}', {}),
            (b'{"foo1": "bar1"}', {})
        ]

        batches = self.queue.get_batches()

        self.assertEqual([
            {"foo": "bar"},
            {"foo1": "bar1"}
        ], batches)
        self.client.get_prefix.assert_called_once_with(
            '/ngs/batch/switch1/input/',
            sort_order='ascend', sort_target='create')

    def test_record_result(self):
        batches = [
            {"result_key": "result1", "input_key": "input1"},
            {"result_key": "result2", "input_key": "input2"},
        ]

        self.queue.record_result("asdf", batches)

        self.assertEqual(2, self.client.create.call_count)
        self.client.create.assert_has_calls([
            mock.call(
                "result1",
                b'{"input_key": "input1", '
                b'"result": "asdf", "result_key": "result1"}'),
            mock.call(
                "result2",
                b'{"input_key": "input2", '
                b'"result": "asdf", "result_key": "result2"}'),
        ])
        self.assertEqual(2, self.client.delete.call_count)
        self.client.delete.assert_has_calls([
            mock.call("input1"),
            mock.call("input2"),
        ])

    @mock.patch.object(batching.SwitchQueue, "_get_raw_batches")
    def test_acquire_worker_lock_timeout(self, mock_get):
        mock_get.return_value = ["work"]
        lock = mock.MagicMock()
        lock.acquire.return_value = False
        self.client.lock.return_value = lock

        wait = tenacity.wait_none()
        self.assertRaises(
            tenacity.RetryError,
            self.queue.acquire_worker_lock,
            wait=wait, acquire_timeout=0.05)

    @mock.patch.object(batching.SwitchQueue, "_get_raw_batches")
    def test_acquire_worker_lock_no_work(self, mock_get):
        mock_get.side_effect = [["work"], None]
        lock = mock.MagicMock()
        lock.acquire.return_value = False
        self.client.lock.return_value = lock

        wait = tenacity.wait_none()
        result = self.queue.acquire_worker_lock(
            wait=wait, acquire_timeout=0.05)

        self.assertIsNone(result)
        self.assertEqual(2, mock_get.call_count)
        self.assertEqual(2, lock.acquire.call_count)

    @mock.patch.object(batching.SwitchQueue, "_get_raw_batches")
    def test_acquire_worker_lock_success(self, mock_get):
        mock_get.return_value = ["work"]
        lock = mock.MagicMock()
        lock.acquire.side_effect = [False, False, True]
        self.client.lock.return_value = lock

        wait = tenacity.wait_none()
        result = self.queue.acquire_worker_lock(
            wait=wait, acquire_timeout=0.05)

        self.assertEqual(lock, result)
        self.assertEqual(2, mock_get.call_count)
        self.assertEqual(3, lock.acquire.call_count)


class SwitchBatchTest(fixtures.TestWithFixtures):
    def setUp(self):
        super(SwitchBatchTest, self).setUp()
        self.cfg = self.useFixture(config_fixture.Config())

        self.queue = mock.Mock()
        self.switch_name = "switch1"
        self.batch = batching.SwitchBatch(
            self.switch_name, switch_queue=self.queue)

    @mock.patch.object(batching.SwitchBatch, "_spawn")
    def test_do_batch(self, mock_spawn):
        callback = mock.MagicMock()
        callback.return_value = "output"
        self.queue.add_batch_and_wait_for_result.return_value = callback
        result = self.batch.do_batch(["cmd1"], "fn")

        self.assertEqual("output", result)
        self.assertEqual(1, mock_spawn.call_count)
        self.queue.add_batch_and_wait_for_result.assert_called_once_with(
            ["cmd1"])
        callback.assert_called_once_with(timeout=300)

    def test_do_execute_pending_batches_skip(self):
        self.queue.get_batches.return_value = []
        batch = mock.MagicMock()

        result = self.batch._execute_pending_batches(batch)

        self.assertIsNone(result)

    def test_do_execute_pending_batches_success(self):
        self.queue.get_batches.return_value = [
            {"cmds": ["cmd1", "cmd2"]},
            {"cmds": ["cmd3", "cmd4"]},
        ]
        batch = mock.MagicMock()
        lock = mock.MagicMock()
        self.queue.acquire_worker_lock.return_value = lock

        self.batch._execute_pending_batches(batch)

        batch.assert_called_once_with(['cmd1', 'cmd2', 'cmd3', 'cmd4'])
        self.queue.acquire_worker_lock.assert_called_once_with()
        lock.__enter__.assert_called_once_with()
        lock.__exit__.assert_called_once_with(None, None, None)
