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

import etcd3gw
import eventlet
from oslo_log import log as logging
from oslo_utils import uuidutils

LOG = logging.getLogger(__name__)


class BatchList(object):
    EXEC_LOCK = "/ngs/batch/%s/execute_lock"
    INPUT_PREFIX = "/ngs/batch/%s/input/"
    INPUT_ITEM_KEY = "/ngs/batch/%s/input/%s"
    RESULT_ITEM_KEY = "/ngs/batch/%s/output/%s"

    def __init__(self, switch_name, etcd_client=None):
        self.switch_name = switch_name
        self.client = etcd_client
        if self.client is None:
            # TODO(johngarbutt) url that supports cert config is better
            self.client = etcd3gw.client(
                host="10.225.1.1", port=2381)
        atexit.register(self.client.close)

    def add_batch(self, cmds):
        """Clients add batch, given key to wait on for completion"""
        # TODO(johngarbutt) update this so we preserve insertion order
        uuid = uuidutils.generate_uuid()
        result_key = self.RESULT_ITEM_KEY % (self.switch_name, uuid)
        input_key = self.INPUT_ITEM_KEY % (self.switch_name, uuid)
        # TODO(johngarbutt) add a date it was added, so it can timeout?
        event = {
            "uuid": uuid,
            "result_key": result_key,
            "cmds": cmds,
        }
        value = json.dumps(event).encode("utf-8")
        success = self.client.create(input_key, value)
        if not success:
            raise Exception("failed to add batch to key: %s", input_key)
        keys = self.client.get(input_key)
        if len(keys) != 1:
            raise Exception("failed find value we just added")
        LOG.debug("written to key %s", input_key)
        return {
            "version": keys[0][1]["create_revision"],
            "result_key": result_key
        }

    def execute_pending_batches(self, get_connection, do_batch, save_config):
        """Execute all batches currently registered.

        Typically called by every caller of add_batch.
        Often a noop if all batches are already executed.
        """
        input_prefix = self.INPUT_PREFIX % self.switch_name
        batches = self.client.get_prefix(input_prefix)
        if not batches:
            LOG.debug("Skipped execution for %s", self.switch_name)
            return

        LOG.debug("Getting lock to execute %d batches", len(batches))
        lock_ttl_seconds = 30
        lock_name = self.EXEC_LOCK % self.switch_name
        lock = self.client.lock(lock_name, lock_ttl_seconds)

        with lock.acquire() as lock:
            LOG.debug("got lock %s", lock_name)

            # Fetch fresh list now we have the lock
            batches = self.client.get_prefix(input_prefix)
            if not batches:
                LOG.debug("No batches to execute %s", self.switch_name)
                return
            LOG.debug("Starting to execute %d batches", len(batches))

            with get_connection() as connection:
                connection.enable()
                lock.refresh()

                # Try to apply all the batches
                results = {}
                for value, metadata in batches:
                    batch = json.loads(value.decode('utf-8'))
                    input_key = metadata["key"]

                    LOG.debug("executing: %s %s", batch, metadata)
                    result = do_batch(connection, batch['cmds'])
                    results[input_key] = {
                        'result': result,
                        'input_key': input_key,
                        'result_key': batch['result_key'],
                    }
                    LOG.debug("got result: %s", results[input_key])
                    lock.refresh()

                # Save the changes we made
                # TODO(johngarbutt) maybe undo failed config first? its tricky
                LOG.debug("Trying to save config")
                save_config(connection)
                LOG.debug("Saved config")

                # Config can take a while
                lock.refresh()
                LOG.debug("lock refreshed")

                # Now we have saved the config,
                # tell the waiting threads we are done
                LOG.debug("write results to etcd")
                for input_key, result_dict in results.items():
                    # TODO(johngarbutt) more careful about key versions
                    success = self.client.create(
                        result_dict['result_key'],
                        json.dumps(result_dict['result']).encode('utf-8'))
                    if not success:
                        # TODO(johngarbutt) what can we do here?
                        LOG.error("failed to report batch result for: %s",
                                  batch)
                    delete_success = self.client.delete(input_key)
                    if not delete_success:
                        LOG.error("unable to delete input key: %s",
                                  input_key)

        LOG.debug("end of lock %s", lock_name)

    def get_result(self, result_key, version):
        LOG.debug("fetching key %s", result_key)
        # TODO(johngarbutt) need to look in the event!
        raw, metadata = self.client.get(result_key)
        if metadata is None:
            LOG.error("Failed to fetch result for %s", result_key)
            raise Exception("can't find result: %s", result_key)
        batch_result = json.loads(raw.encode('utf-8'))
        LOG.debug("deleting key, now we have result: %s", result_key)
        is_deleted = self.client.delete(result_key)
        if not is_deleted:
            LOG.error("Unable to delete key %s", result_key)
        return batch_result

    def wait_for_result(self, result_key, version):
        """Blocks until result is received"""
        LOG.debug("starting to watch key: %s", result_key)
        events, cancel = self.client.watch(result_key,
                                           start_revision=(version + 1))
        eventlet.sleep(0)

        # TODO(johngarbutt) timeout?
        for event in events:
            LOG.debug("Got: event %s", event)
            cancel()

        return self.get_result(result_key, version)
