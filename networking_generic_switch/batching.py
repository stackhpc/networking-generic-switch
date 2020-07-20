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

import atexit
import json

import etcd3
from oslo_log import log as logging
from oslo_utils import uuidutils

LOG = logging.getLogger(__name__)


class BatchList(object):
    EXEC_LOCK = "/ngs/batch/%s/exec_lock"
    INPUT_PREFIX = "/ngs/batch/%s/input/"
    INPUT_ITEM_KEY = "/ngs/batch/%s/input/%s"
    RESULT_ITEM_KEY = "/ngs/batch/%s/output/%s"

    def __init__(self, switch_name, etcd_client=None):
        self.switch_name = switch_name
        self.client = etcd_client
        if self.client is None:
            # TODO(johngarbutt) url that supports cert config is better
            self.client = etcd3.client(
                host="localhost", port=2379)
        atexit.register(self.client.close)

    def add_batch(self, cmds):
        """Clients add batch, given key to wait on for completion"""
        uuid = uuidutils.generate_uuid()
        result_key = self.RESULT_ITEM_KEY.format(self.switch_name, uuid)
        input_key = self.INPUT_ITEM_KEY.format(self.switch_name, uuid)
        event = {
            "uuid": uuid,
            "result_key": result_key,
            "cmds": cmds,
        }
        value = json.dumps(event).encode("utf-8")
        success = self.client.put_if_not_exists(input_key, value)
        if not success:
            raise Exception("failed to add batch")
        _, metadata = self.client.get(input_key)
        if metadata is None:
            raise Exception("failed find value we just added")
        return {
            "version": metadata.create_revision,
            "result_key": result_key
        }

    def execute_pending_batches(self, get_connection, do_batch, save_config):
        """Execute all batches currently registered.

        Typically called by every caller of add_batch.
        Often a noop if all batches are already executed.
        """
        input_prefix = self.INPUT_PREFIX.format(self.switch_name)
        batches = self.client.get_prefix(input_prefix)
        if not batches:
            LOG.debug("Skipped execution for %s", self.switch_name)
            return

        LOG.debug("Starting to execute %d batches", len(batches))
        lock_ttl_seconds = 60
        lock_acquire_timeout = 300
        lock = self.client.lock(self.EXEC_LOCK.format(self.switch_name),
                                lock_ttl_seconds)

        lock.acquire(lock_acquire_timeout)
        try:
            with get_connection() as connection:
                connection.enable()
                lock.refresh()

                # Try to apply all the batches
                completed_keys = []
                results = {}
                for value, metadata in batches:
                    batch = json.loads(value.decode('utf-8'))
                    result = do_batch(connection, batch.cmds)
                    results[metadata.key] = result
                    completed_keys.append(metadata)
                    lock.refresh()

                # Save the changes we made
                # TODO(johngarbutt) maybe undo failed config first? its tricky
                save_config(connection)

                # Config can take a while
                lock.refresh()

                # Now we have saved the config,
                # tell the waiting threads we are done
                for key_metadata in completed_keys:
                    # TODO(johngarbutt) more careful about key versions
                    success = self.client.put_if_not_exists(batch.result_key,
                                                            json.dumps(result))
                    if not success:
                        # TODO(johngarbutt) what can we do here?
                        LOG.error("failed to report batch result for: %s",
                                  batch)
                    delete_success = self.client.delete(key_metadata.key)
                    if not delete_success:
                        LOG.error("unable to delete input key: %s",
                                  key_metadata.key)
        finally:
            lock.release()

    def get_result(self, result_key, version):
        """Blocks until result is received"""
        events, cancel = self.client.watch(result_key,
                                           start_revision=(version + 1))
        for event in events:
            cancel()
            LOG.debug("Got: event %s", event)

        # TODO(johngarbutt) need to look in the event!
        raw, metadata = self.client.get(result_key)
        batch_result = json.loads(raw.encode('utf-8'))
        is_deleted = self.client.delete(result_key)
        if not is_deleted:
            LOG.error("Unable to delete key %s", result_key)
        return batch_result
