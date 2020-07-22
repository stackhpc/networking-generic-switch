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

import json

import etcd3gw
from oslo_log import log as logging
from oslo_utils import uuidutils
import tenacity

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
                host="10.225.1.1", port=2379)

    def add_batch(self, cmds):
        """Clients add batch, given key to wait on for completion."""
        # TODO(johngarbutt) update this so we preserve insertion order
        uuid = uuidutils.generate_uuid()
        result_key = self.RESULT_ITEM_KEY % (self.switch_name, uuid)
        input_key = self.INPUT_ITEM_KEY % (self.switch_name, uuid)

        # Start waiting on the key we expect to be created
        # Do this before anyone knows to create it, to avoid racing

        result_events, watch_cancel = self.client.watch(result_key)

        # TODO(johngarbutt) add a lease so this times out?
        event = {
            "uuid": uuid,
            "input_key": input_key,
            "result_key": result_key,
            "cmds": cmds,
        }
        value = json.dumps(event).encode("utf-8")
        success = self.client.create(input_key, value)
        if not success:
            raise Exception("failed to add batch to key: %s", input_key)
        LOG.debug("written input key %s", input_key)

        return result_key, result_events, watch_cancel

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
        lock_ttl_seconds = 300
        lock_name = self.EXEC_LOCK % self.switch_name
        lock = self.client.lock(lock_name, lock_ttl_seconds)

        @tenacity.retry(
            # Log a message after each failed attempt.
            after=tenacity.after_log(LOG, logging.DEBUG),
            # Retry if we haven't got the lock yet
            retry=tenacity.retry_if_result(lambda x: x is False),
            # Stop after the configured timeout.
            stop=tenacity.stop_after_delay(400),
            # Wait for the configured interval between attempts.
            wait=tenacity.wait_fixed(2),
        )
        def _acquire_lock_with_retry():
            lock_acquired = lock.acquire()
            if lock_acquired:
                return True

            # Stop waiting for the lock if there is nothing to do
            work = self.client.get_prefix(input_prefix)
            if not work:
                return None

            # Trigger a retry
            return False

        # Be sure we got the lock
        got_lock = _acquire_lock_with_retry()
        if not got_lock or not lock.is_acquired():
            raise Exception("unable to get lock: %s", lock_name)

        # be sure to drop the lock when we are done
        results = {}
        with lock:
            LOG.debug("got lock %s", lock_name)

            # Fetch fresh list now we have the lock
            # and order the list so we execute in order added
            batches = self.client.get_prefix(input_prefix,
                                             sort_order="ascend",
                                             sort_target="create")
            if not batches:
                LOG.debug("No batches to execute %s", self.switch_name)
                return

            LOG.debug("Starting to execute %d batches", len(batches))
            # TODO(johngarbutt) seem to have two threads getting here!!
            keys = [metadata["key"] for value, metadata in batches]
            LOG.debug("Starting to execute keys: %s", keys)
            lock.refresh()

            with get_connection() as connection:
                connection.enable()
                lock.refresh()

                # Try to apply all the batches
                # and save all the results
                all_cmds = []
                for value, metadata in batches:
                    batch = json.loads(value.decode('utf-8'))
                    input_key = metadata["key"]
                    all_cmds += batch['cmds']
                    # LOG.debug("executing: %s %s", batch, metadata)
                    results[input_key] = {
                        'result': "TODO",
                        'input_key': input_key,
                        'result_key': batch['result_key'],
                    }
                    # LOG.debug("got result: %s", results[input_key])
                    # lock.refresh()
                result = do_batch(connection, all_cmds)
                LOG.debug("got result: %s", result)

                # Save the changes we made
                # TODO(johngarbutt) maybe undo failed configs first?
                LOG.debug("Start save config")
                save_config(connection)
                LOG.debug("Finish save config")

            lock.refresh()
            LOG.debug("lock refreshed")

            # Now we have saved the config,
            # tell the waiting threads we are done
            LOG.debug("write results to etcd")
            for input_key, result_dict in results.items():
                # TODO(johngarbutt) create this with a lease
                #   so auto delete if no one gets the result?
                success = self.client.create(
                    result_dict['result_key'],
                    json.dumps(result_dict['result']).encode('utf-8'))
                if not success:
                    # TODO(johngarbutt) should we fail to delete the key at
                    #  this point?
                    LOG.error("failed to report batch result for: %s",
                              batch)
                else:
                    LOG.debug("reported result: %s", input_key)
                # Stop the next lock holder thinking they need
                # to do this again
                delete_success = self.client.delete(input_key)
                if not delete_success:
                    LOG.error("unable to delete input key: %s",
                              input_key)
                else:
                    LOG.debug("deleted input key: %s", input_key)
                lock.refresh()

            LOG.debug("Finished executing keys: %s", keys)

        LOG.debug("end of lock %s", lock_name)

    def get_result(self, result_key, **kwargs):
        LOG.debug("fetching key %s", result_key)
        # TODO(johngarbutt) need to look in the event!
        results = self.client.get(result_key, metadata=True)
        if len(results) != 1:
            LOG.error("Failed to fetch result for %s", result_key)
            raise Exception("can't find result: %s", result_key)
        raw = results[0][0]
        batch_result = json.loads(raw.encode('utf-8'))

        LOG.debug("deleting key, now we have result: %s", result_key)
        is_deleted = self.client.delete(result_key)
        if not is_deleted:
            LOG.error("Unable to delete key %s", result_key)
        return batch_result

    def wait_for_result(self, result_key, result_events, watch_cancel):
        """Blocks until result is received"""
        # TODO(johngarbutt) need to timeout this?
        for event in result_events:
            LOG.debug("Got event: %s", event)
            # TODO(johngarbutt): check this is the event we wanted!
            watch_cancel()

        return self.get_result(result_key)
