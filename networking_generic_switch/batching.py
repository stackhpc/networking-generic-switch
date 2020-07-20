import json

from oslo_utils import uuidutils
from oslo_log import log as logging
import etcd3

LOG = logging.getLogger(__name__)


class BatchList(object):
    EXEC_LOCK =  "/ngs/batch/%s/exec_lock"
    INPUT_PREFIX = "/ngs/batch/%s/input/"
    INPUT_ITEM_KEY = "/ngs/batch/%s/input/%s"
    RESULT_ITEM_KEY = "/ngs/batch/%s/output/%s"

    def __init__(self, switch_name, etcd_host, etcd_port):
        self.switch_name = switch_name
        # TODO url that supports cert config is better
        self.client = etcd3.client(host=etcd_host,
                                   port=etcd_port)

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
        success = self.client.put_if_not_exists(input_key, json.dumps(event))
        if not success:
            raise Exception("failed to add batch")
        return result_key

    def execute_pending_batches(self, do_batch, save_config):
        """Execute all batches currently registered.

        Typically called by every caller of add_batch.
        Often a noop if all batches are already executed."""
        input_prefix = self.INPUT_PREFIX.format(self.switch_name)
        batches = self.client.get_prefix(input_prefix)
        if not batches:
            LOG.debug("Skipped execution for %s", self.switch_name)
            return

        lock_ttl_seconds = 60
        lock_acquire_timeout = 300
        lock = self.client.lock(self.EXEC_LOCK.format(self.switch_name),
                                lock_ttl_seconds)

        lock.acquire(lock_acquire_timeout)
        try:
            # Try to apply all the batches
            success_keys = []
            for value, metadata in batches:
                batch = json.loads(value)
                result = do_batch(batch.cmds)
                success = self.client.put_if_not_exists(batch.result_key,
                                                        json.dumps(result))
                if not success:
                    # TODO: what can we do here?
                    LOG.error("failed to report batch result for: %s", batch)
                else:
                    success_keys.append(metadata)

            # Config can take a while
            lock.refresh()

            # Save the changes we made
            # TODO: maybe undo failed config first? its tricky
            save_config()

            # Config can take a while
            lock.refresh()

            # Now we have saved the config,
            # tell the waiting threads we are done
            for key_metadata in success_keys:
                # TODO: could be more careful about key versions
                success = self.client.delete(key_metadata.key)
                if not success:
                    LOG.error("unable to delete key: %s", key_metadata.key)
        finally:
            lock.release()
