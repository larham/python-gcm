from datetime import datetime
import time
from django.utils.encoding import smart_str
from gcm import GCM
from gcm.gcm import GCMRetriableException

MY_EXCELLENT_GCM_KEY = 'my excellent gcm key'   # replace with your key, or supply it via another means


def send_notification(ids, devices_by_reg_id, payload, max_attempts=3):
    """
    Send a message to multiple devices via Google GCM system's multicast feature.
    Since the gcm system provides feedback as a summary after attempting all messages,
     we record success/failure of a given device
    within this routine.
    @param ids: list of keys within devices_by_reg_id
    @param devices_by_reg_id: dictionary of device (mobile/tablet etc.) that will receive notification
    @param payload: message to send
    @return True if ALL ids were handled by GCM (success or failure, but handled), False otherwise (such as a network failure)
    """

    if not ids or not payload or not devices_by_reg_id:
        return False

    # assume NO collapsing of messages together--try to send all to device when device comes back online.
    # note that collapse_key cannot be None if time_to_live is not None
    collapse_key = str(datetime.now())
    delay_while_idle = False
    time_to_live = 3600

    for i in xrange(max_attempts):
        try:
            gcm_response = GCM(MY_EXCELLENT_GCM_KEY).request_json(
                ids, payload, collapse_key, delay_while_idle, time_to_live)

            parse_response(devices_by_reg_id, gcm_response, ids)

            should_retry = gcm_response.has_resends()
            if should_retry:
                ids = gcm_response.get_resend_ids(ids)  # reset ids for next try
                if i < max_attempts - 1:
                    time.sleep(0.20) # TODO back off exponentially
                else:
                    break  # record failures below
            else:
                return True  # FINISHED!  successes already recorded

        except GCMRetriableException:
            if i < max_attempts - 1:
                time.sleep(0.20) # TODO back off exponentially
            else:
                break

        except Exception as e:
            print('problem with gcm: %s' % smart_str(e))
            break

    # the attempt failed if we got here.
    for fail_id in ids:
        if devices_by_reg_id.has_key(fail_id):
            d = devices_by_reg_id[fail_id]
            # record_fail(d.user_id, d.id)
    return False

def parse_response(devices_by_reg_id, gcm_response, ids):
    for (old_reg_id, canonical_id) in gcm_response.get_canonical_ids(ids):
        if devices_by_reg_id.has_key(old_reg_id):
            d = devices_by_reg_id[old_reg_id]
            d.registration_id = canonical_id # Replace reg_id with canonical_id in your database
            d.save()
    for old_invalid_id in gcm_response.get_unregister_errors(ids):
        if devices_by_reg_id.has_key(old_invalid_id):
            d = devices_by_reg_id[old_invalid_id]
            d.registration_id = ''
            d.save()  # this should happen right away, since all future notifications should be skipped
    for success_id in gcm_response.get_successes(ids):
        if devices_by_reg_id.has_key(success_id):
            d = devices_by_reg_id[success_id]
            # record_success(d.user_id, d.id)

