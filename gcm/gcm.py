# from https://github.com/geeknam/python-gcm on 30 aug 2012
import urllib
import urllib2
import json
import time
import random
from django.utils.encoding import smart_str

GCM_URL = 'https://android.googleapis.com/gcm/send'


class GCMException(Exception): pass
class GCMNoRetryException(Exception): pass
class GCMRetriableException(Exception): pass
class GCMMalformedJsonException(GCMNoRetryException): pass
class GCMConnectionException(GCMRetriableException): pass
class GCMAuthenticationException(GCMNoRetryException): pass
class GCMTooManyRegIdsException(GCMNoRetryException): pass
class GCMNoCollapseKeyException(GCMNoRetryException): pass
class GCMInvalidTtlException(GCMNoRetryException): pass

# Exceptions from Google responses
class GCMMissingRegistrationException(GCMNoRetryException): pass
class GCMMismatchSenderIdException(GCMNoRetryException): pass
class GCMNotRegisteredException(GCMNoRetryException): pass
class GCMMessageTooBigException(GCMNoRetryException): pass
class GCMInvalidRegistrationException(GCMNoRetryException): pass
class GCMUnavailableException(GCMRetriableException): pass

class GCM(object):

    # Timeunit is milliseconds.
    BACKOFF_INITIAL_DELAY_MS = 1000
    MAX_BACKOFF_DELAY_MS = 1024000

    def __init__(self, api_key):
        self.api_key = api_key

    def construct_payload(self, registration_ids, data=None, collapse_key=None,
                            delay_while_idle=False, time_to_live=None, is_json=True):
        """
        Construct the dictionary mapping of parameters.
        Encodes the dictionary into JSON if for json requests.
        Helps appending 'data.' prefix to the plaintext data: 'hello' => 'data.hello'

        :return constructed dict or JSON payload
        :raises GCMInvalidTtlException: if time_to_live is invalid
        :raises GCMNoCollapseKeyException: if collapse_key is missing when time_to_live is used
        """

        if time_to_live:
            if time_to_live > 2419200 or time_to_live < 0:
                raise GCMInvalidTtlException("Invalid time to live value")

        if is_json:
            payload = {'registration_ids': registration_ids}
            if data:
                payload['data'] = data
        else:
            payload = {'registration_id': registration_ids}
            if data:
                for k in data.keys():
                    data['data.%s' % k] = data.pop(k)
                payload.update(data)

        if delay_while_idle:
            payload['delay_while_idle'] = delay_while_idle

        if time_to_live:
            payload['time_to_live'] = time_to_live
            if collapse_key is None:
                raise GCMNoCollapseKeyException("collapse_key is required when time_to_live is provided")

        if collapse_key:
            payload['collapse_key'] = collapse_key

        if is_json:
            payload = json.dumps(payload)

        return payload

    def make_request(self, data, is_json=True):
        """
        Makes a HTTP request to GCM servers with the constructed payload

        :param data: return value from construct_payload method
        :raises GCMMalformedJsonException: if malformed JSON request found
        :raises GCMAuthenticationException: if there was a problem with authentication, invalid api key
        :raises GCMConnectionException: if GCM is screwed
        """

        headers = {
            'Authorization': 'key=%s' % self.api_key,
        }
        # Default Content-Type is defaulted to application/x-www-form-urlencoded;charset=UTF-8
        if is_json:
            headers['Content-Type'] = 'application/json'

        if not is_json:
            data = urllib.urlencode(data)
        req = urllib2.Request(GCM_URL, data, headers)

        try:
            response = urllib2.urlopen(req).read()
        except urllib2.HTTPError as e:
            if e.code == 400:
                raise GCMMalformedJsonException("JSON could not be parsed (400)")
            elif e.code == 401:
                raise GCMAuthenticationException("Authentication error (401)")
            elif e.code == 503 or e.code == 500:
                raise GCMUnavailableException("Unavailable (%d)" % e.code)
            else:
                raise GCMConnectionException("Http error connecting to GCM: %s" % smart_str(e))
        except IOError as e:
            raise GCMConnectionException("IOError attempting GCM push: %s" % smart_str(e))

        except Exception as e:
            raise GCMConnectionException("Error attempting GCM push: %s" % smart_str(e))

        return response

    def raise_error(self, error):
        if error == 'InvalidRegistration':
            raise GCMInvalidRegistrationException("Registration ID is invalid")
        elif error == 'Unavailable':
            # Plain-text requests will never return Unavailable as the error code.
            # http://developer.android.com/guide/google/gcm/gcm.html#error_codes
            raise GCMUnavailableException("Server unavailable. Resend the message")
        elif error == 'NotRegistered':
            raise GCMNotRegisteredException("Registration id is not valid anymore")
        elif error == 'MismatchSenderId':
            raise GCMMismatchSenderIdException("A Registration ID is tied to a certain group of senders")
        elif error == 'MessageTooBig':
            raise GCMMessageTooBigException("Message exceeds 4096 bytes")
        else:
            raise GCMException(smart_str(error))

    def handle_plaintext_response(self, response):
        if not response:
            raise GCMException("no response")

        # Split response by line
        response_lines = response.strip().split('\n')
        if len(response_lines) == 0:
            raise GCMException("no response")

        # Split the first line by =
        key, value = response_lines[0].split('=')
        if key == 'Error':
            self.raise_error(value)
        else:
            if len(response_lines) == 2:
                return response_lines[1].split('=')[1]
            else:
                return

    def extract_unsent_reg_ids(self, info):
        if 'errors' in info and 'Unavailable' in info['errors']:
            return info['errors']['Unavailable']
        else:
            return []

    def request_plaintext(self, registration_id, data=None, collapse_key=None,
                            delay_while_idle=False, time_to_live=None, tries=5):
        """
        Makes a plaintext request to GCM servers, including a (blocking) retry loop that
        can take up to 17 minutes with default 4 retries.

        :param tries number of attempts.  0 will raise exception. 1 for one attempt but no retries, etc.
        :param registration_id: string of the registration id
        :param data: dict mapping of key-value pairs of messages
        :return dict of response body from Google including multicast_id, success, failure, canonical_ids, etc
        :raises GCMMissingRegistrationException: if registration_id is not provided
        """

        if not registration_id:
            raise GCMMissingRegistrationException("Missing registration_id")

        if tries == 0:
            raise GCMException('number of tries 0: why did you call this?')

        payload = self.construct_payload(
            registration_id, data, collapse_key,
            delay_while_idle, time_to_live, False
        )

        attempt = 0
        backoff = self.BACKOFF_INITIAL_DELAY_MS
        for attempt in range(tries):
            try:
                response = self.make_request(payload, is_json=False)
                return self.handle_plaintext_response(response)
            except GCMUnavailableException:
                sleep_time = backoff / 2 + random.randrange(backoff)
                time.sleep(float(sleep_time) / 1000)
                if 2 * backoff < self.MAX_BACKOFF_DELAY_MS:
                    backoff *= 2
                else:
                    backoff = self.MAX_BACKOFF_DELAY_MS

        raise IOError("Failed to make GCM request after %d attempts" % attempt)

    def request_json(self, registration_ids, data=None, collapse_key=None,
                        delay_while_idle=False, time_to_live=None):
        """
        Makes a JSON request to GCM servers. Caller should parse response to handle
        any ID resets, removals, and also the caller is responsible for retries.

        :param time_to_live secs
        :param registration_ids: list of the registration ids
        :param data: dict mapping of key-value pairs of messages
        :return custom response object that includes lists of successes, retry failures, canonical_ids, etc
        :raises GCMMissingRegistrationException: if the list of registration_ids exceeds 1000 items
        """
        if not registration_ids:
            raise GCMMissingRegistrationException("Missing registration_ids")
        if len(registration_ids) > 1000:
            raise GCMTooManyRegIdsException("Exceeded number of registration_ids")
        if not data or len(data) == 0:
            raise GCMException('no data to send')

        payload = self.construct_payload(
            registration_ids, data, collapse_key,
            delay_while_idle, time_to_live
        )
        response = self.make_request(payload, is_json=True)
        return GCM_response_wrapper(response)

class GCM_response_wrapper(object):
    """
    encapsulate the json response from GCM; useful for multicast requests.
    You should iterate through 3 lists in this result:
        * unregister any dead IDs from get_unregister_errors
        * reset any replacement IDs returned from get_canonical_ids()
        * resend messages that could not be sent (after exponential backoff time) from get_resend_ids()
    """
    def __init__(self, json_response):
        self.my_json = json.loads(json_response)

    def has_error(self):
        return self.my_json['failure'] > 0

    def has_canonical(self):
        return self.my_json['canonical_ids'] > 0

    def has_success(self):
        return self.my_json['success'] > 0

    def has_resends(self):
        return self.has_error() and len(self._get_resends()) > 0

    def get_successes(self, reg_ids):
        """
        @return list( success_id )
        """
        if not reg_ids or len(reg_ids) == 0:
            return []
        if not self.has_success():
            return []

        num_incoming = len(reg_ids)
        num_results = len(self.my_json['results'])
        if num_incoming != num_results:
          print('expected number of incoming reg_ids: %i to equal number of results: %i' % (num_incoming, num_results))

        successes = []
        i = 0
        for item in self.my_json['results']:
            if item.has_key('message_id'):
                if i < num_incoming:
                    successes.append(reg_ids[i])
                else:
                    break
            i += 1
        return successes

    def get_unregister_errors(self, reg_ids):
        """
        either not registered or invalid registration: remove these registration ids from further attempts.
        @return list( invalid_reg_id )
        """
        if not reg_ids or len(reg_ids) == 0:
            return []
        if not self.has_error():
            return []

        num_incoming = len(reg_ids)
        num_results = len(self.my_json['results'])
        if num_incoming != num_results:
          print('expected number of incoming reg_ids: %i to equal number of results: %i' % (num_incoming, num_results))

        errors = []
        i = 0
        for item in self.my_json['results']:
            if item.has_key('error') and (item['error'] == 'NotRegistered' or item['error'] == 'InvalidRegistration'):
                if i < num_incoming:
                    errors.append(reg_ids[i])
                else:
                    break
            i += 1
        return errors

    def _get_resends(self):
        """
        Unavailable error means we need to resend after exponential backoff period
        @return list( (line_num, error_msg) )
        """
        if not self.has_error():
            return []

        errors = []
        i = 0
        for item in self.my_json['results']:
            if item.has_key('error') and item['error'] == 'Unavailable':
                errors.append((i, item['error']))
            i += 1
        return errors

    def get_resend_ids(self, reg_ids):
        """
        use error line numbers to select from provided list.
        @return list( ids that should be resent )
        """
        if not reg_ids or len(reg_ids) == 0:
            return []
        num_incoming = len(reg_ids)
        num_results = len(self.my_json['results'])
        if num_incoming != num_results:
            print('expected number of incoming reg_ids: %i to equal number of results: %i' % (num_incoming, num_results))

        resends = self._get_resends()
        ids = []
        for (line_num, err) in resends:
            if line_num < num_incoming:
                ids.append(reg_ids[line_num])
            else:
                break
        return ids

    def get_canonical_ids(self, reg_ids):
        """
        get a list of replacement (canonical) registration ids.
        @return list( (old_id, canonical_id) )
        """
        if not reg_ids or len(reg_ids) == 0:
            return []
        if not self.has_canonical():
            return []

        num_incoming = len(reg_ids)
        num_results = len(self.my_json['results'])
        if num_incoming != num_results:
            print('expected number of incoming reg_ids: %i to equal number of results: %i' % (num_incoming, num_results))

        canonical = []
        i = 0
        for item in self.my_json['results']:
            if item.has_key('registration_id'):
                if i < num_incoming:
                    canonical.append((reg_ids[i], item['registration_id']))
                else:
                    break
            i += 1
        return canonical
