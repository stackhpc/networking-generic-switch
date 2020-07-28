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
import queue

import etcd3gw
from etcd3gw import watch
import eventlet
from oslo_log import log as logging
from oslo_utils import netutils
from oslo_utils import uuidutils
import tenacity

LOG = logging.getLogger(__name__)


class SwitchQueue(object):
    INPUT_PREFIX = "/ngs/batch/%s/input/"
    INPUT_ITEM_KEY = "/ngs/batch/%s/input/%s"
    RESULT_ITEM_KEY = "/ngs/batch/%s/output/%s"
    EXEC_LOCK = "/ngs/batch/%s/execute_lock"

    def __init__(self, switch_name, etcd_client):
        self.switch_name = switch_name
        self.client = etcd_client

    def add_batch_and_wait_for_result(self, cmds):
        """Clients add batch, given key events.

        Each batch is given an uuid that is used to generate both
        and input and result key in etcd.

        First we watch for any results, second we write the input
        in a location that the caller of get_batches will be looking.

        No locks are required when calling this function to send work
        to the workers, and start waiting for results.

        Returns a function that takes a timeout parameter to wait
        for the default.
        """

        uuid = uuidutils.generate_uuid()
        result_key = self.RESULT_ITEM_KEY % (self.switch_name, uuid)
        input_key = self.INPUT_ITEM_KEY % (self.switch_name, uuid)

        # Start waiting on the key we expect to be created and
        # start watching before writing input key to avoid racing
        watcher, get_result = self._watch_for_result(result_key)

        batch = {
            "uuid": uuid,
            "input_key": input_key,
            "result_key": result_key,
            "cmds": cmds,
        }
        value = json.dumps(batch, sort_keys=True).encode("utf-8")
        try:
            # TODO(johngarbutt) add a lease so this times out?
            success = self.client.create(input_key, value)
        except Exception:
            # Be sure to free watcher resources
            watcher.stop()
            raise

        # Be sure to free watcher resources on error
        if not success:
            watcher.stop()
            raise Exception("failed to add batch to key: %s", input_key)

        LOG.debug("written input key %s", input_key)
        return get_result

    def _watch_for_result(self, result_key):
        # Logic based on implementation of client.watch_once()
        event_queue = queue.Queue()

        def callback(event):
            event_queue.put(event)

        watcher = watch.Watcher(self.client, result_key, callback)

        def wait_for_key(timeout):
            try:
                event = event_queue.get(timeout=timeout)
            except queue.Empty:
                raise Exception("timed out waiting for key: %s", result_key)
            finally:
                # NOTE(johngarbutt) this means we need the caller
                # to always watch for the result, or call stop
                # before starting to wait for the key
                watcher.stop()

            LOG.debug("got event: %s", event)
            # TODO(johngarbutt) check we have the create event and result?
            result_dict = self._get_and_delete_result(result_key)
            LOG.debug("got result: %s", result_dict)
            return result_dict["result"]

        return watcher, wait_for_key

    def _get_and_delete_result(self, result_key):
        # called when watch event says the result key should exist
        raw_results = self.client.get(result_key)
        if len(raw_results) != 1:
            raise Exception("unable to find result: %s", result_key)
        raw_value = raw_results[0]
        result_dict = json.loads(raw_value.decode('utf-8'))
        LOG.debug("fetched result for: ", result_key)

        # delete key now we have the result
        delete_success = self.client.delete(result_key)
        if not delete_success:
            LOG.error("unable to delete result key: %s",
                      result_key)
        LOG.debug("deleted result for: ", result_key)
        return result_dict

    def _get_raw_batches(self):
        input_prefix = self.INPUT_PREFIX % self.switch_name
        # Sort order ensures FIFO style queue
        raw_batches = self.client.get_prefix(input_prefix,
                                             sort_order="ascend",
                                             sort_target="create")
        return raw_batches

    def get_batches(self):
        """Return a list of the event dicts written in wait for result.

        This is called both with or without getting a lock to get the
        latest list of work that has send to the per switch queue in
        etcd.
        """
        raw_batches = self._get_raw_batches()
        LOG.debug("found %s batches", len(raw_batches))

        batches = []
        for raw_value, metadata in raw_batches:
            batch = json.loads(raw_value.decode('utf-8'))
            batches.append(batch)
        return batches

    def record_result(self, result, batches):
        """Record the result from executing given batch list.

        We assume that a lock is held before getting a fresh list
        of batches, executing them, and then calling this record
        results function, before finally dropping the lock.
        """
        LOG.debug("write results for %s batches", len(batches))

        # Write results first, so watchers seen these quickly
        for batch in batches:
            batch["result"] = result
            # TODO(johngarbutt) create this with a lease
            #   so auto delete if no one gets the result?
            success = self.client.create(
                batch['result_key'],
                json.dumps(batch, sort_keys=True).encode('utf-8'))
            if not success:
                # TODO(johngarbutt) should we fail to delete the key at
                #  this point?
                LOG.error("failed to report batch result for: %s",
                          batch)

        # delete input keys so the next worker to hold the lock
        # knows not to execute these batches
        for batch in batches:
            input_key = batch["input_key"]
            delete_success = self.client.delete(input_key)
            if not delete_success:
                LOG.error("unable to delete input key: %s",
                          input_key)
            else:
                LOG.debug("deleted input key: %s", input_key)

    def acquire_worker_lock(self, acquire_timeout=300, lock_ttl=120,
                            wait=None):
        """Wait for lock needed to call record_result.

        This blocks until the work queue is empty of the switch lock is
        acquired. If we timeout waiting for the lock we raise an exception.
        """
        lock_name = self.EXEC_LOCK % self.switch_name
        lock = self.client.lock(lock_name, lock_ttl)

        if wait is None:
            wait = tenacity.wait_random(min=1, max=3)

        @tenacity.retry(
            # Log a message after each failed attempt.
            after=tenacity.after_log(LOG, logging.DEBUG),
            # Retry if we haven't got the lock yet
            retry=tenacity.retry_if_result(lambda x: x is False),
            # Stop after timeout.
            stop=tenacity.stop_after_delay(acquire_timeout),
            # Wait between lock retries
            wait=wait,
        )
        def _acquire_lock_with_retry():
            lock_acquired = lock.acquire()
            if lock_acquired:
                return lock

            # Stop waiting for the lock if there is nothing to do
            work = self._get_raw_batches()
            if not work:
                return None

            # Trigger a retry
            return False

        return _acquire_lock_with_retry()


class SwitchBatch(object):
    def __init__(self, switch_name, etcd_url=None, switch_queue=None):
        if switch_queue is None:
            parsed_url = netutils.urlsplit(etcd_url)
            host = parsed_url.hostname
            port = parsed_url.port
            # TODO(johngarbutt): support certs
            protocol = 'https' if parsed_url.scheme.endswith(
                'https') else 'http'
            etcd_client = etcd3gw.client(
                host=host, port=port, protocol=protocol,
                timeout=30)
            self.queue = SwitchQueue(switch_name, etcd_client)
        else:
            self.queue = switch_queue
        self.switch_name = switch_name

    def do_batch(self, cmd_set, batch_fn, timeout=300):
        """Batch up calls to this function to reduce overheads.

        We collect together the iterables in the cmd_set, and
        execute them toegether in a single larger batch.
        This reduces overhead, but does make it harder to track
        down which of the cmds failed.

        :param cmd_set: an iterable of commands
        :param batch_fn: function that takes an iterable of commands
        :return: output string generated by the whole batch
        """

        # request that the cmd_set by executed
        cmd_list = list(cmd_set)
        wait_for_result = self.queue.add_batch_and_wait_for_result(cmd_list)

        def do_work():
            try:
                self._execute_pending_batches(
                    batch_fn)
            except Exception as e:
                LOG.error("failed to run execute batch: %s", e,
                          exec_info=True)
                raise

        self._spawn(do_work)

        # Wait for our result key
        # as the result might be done before the above task starts
        output = wait_for_result(timeout=timeout)
        LOG.debug("Got batch result: %s", output)
        return output

    @staticmethod
    def _spawn(work_fn):
        # TODO(johngarbutt) remove hard eventlet dependency
        #  in a similar way to etcd3gw
        # Sleep to let possible other work to batch together
        eventlet.sleep(0.1)
        # Run all pending tasks, which might be a no op
        # if pending tasks already ran
        eventlet.spawn_n(work_fn)

    def _execute_pending_batches(self, batch_fn):
        """Execute all batches currently registered.

        Typically called by every caller of add_batch.
        Could be a noop if all batches are already executed.
        """
        batches = self.queue.get_batches()
        if not batches:
            LOG.debug("Skipped execution for %s", self.switch_name)
            return
        LOG.debug("Getting lock to execute %d batches for %s",
                  len(batches), self.switch_name)

        lock = self.queue.acquire_worker_lock()
        if lock is None:
            # This means we stopped waiting as the work queue was empty
            LOG.debug("Work list empty for %s", self.switch_name)
            return

        # Check we got the lock
        if not lock.is_acquired():
            raise Exception("unable to get lock for: %s", self.switch_name)

        # be sure to drop the lock when we are done
        with lock:
            LOG.debug("got lock for %s", self.switch_name)

            # Fetch fresh list now we have the lock
            # and order the list so we execute in order added
            batches = self.queue.get_batches()
            if not batches:
                LOG.debug("No batches to execute %s", self.switch_name)
                return

            LOG.debug("Starting to execute %d batches", len(batches))
            all_cmds = []
            for batch in batches:
                all_cmds += batch['cmds']

            # Execute batch function with all the commands
            result = batch_fn(all_cmds)

            # Tell request watchers the result and
            # tell workers which batches have now been executed
            self.queue.record_result(result, batches)

        LOG.debug("end of lock for %s", self.switch_name)
