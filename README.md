python-gcm
======================
[![Build Status](https://secure.travis-ci.org/geeknam/python-gcm.png?branch=master)](http://travis-ci.org/geeknam/python-gcm)

Python client for Google Cloud Messaging for Android (GCM)

Usage
------------
RTFM [here](http://developer.android.com/guide/google/gcm/gcm.html)
        
Basic
```python
gcm = GCM(API_KEY)
data = {'param1': 'value1', 'param2': 'value2'}

# Plaintext request, handles retry loops internally
gcm.request_plaintext(registration_id=reg_id, data=data)

# JSON request; caller should handle retry loops (see multicast below)
reg_ids = ['12', '34', '69']
gcm_response = gcm.request_json(registration_ids=reg_ids, data=data)

# Extra arguments
gcm_response = gcm.request_json(
    registration_ids=reg_ids, data=data,
    collapse_key='up_to_you', delay_while_idle=True, time_to_live=3600
)
```

Error handling
```python
# Plaintext request
reg_id = '12345'
try:
    canonical_id = gcm.request_plaintext(registration_id=reg_id, data=data)
    if canonical_id:
        # Repace reg_id with canonical_id in your database
        entry = entity.filter(registration_id=reg_id)
        entry.registration_id = canonical_id
        entry.save()
except GCMNotRegisteredException:
    # Remove this reg_id from database
    entity.filter(registration_id=reg_id).delete()
except GCMUnavailableException:
    # Resent the message
```

JSON multicast request
For multicasting the same notification to many users, the caller should employ a retry loop.
See client_sample.py, used below as send_notification(). Results from each iteration are processed
by the client.

```python

ids = ['12', '34', '69'] # real gcm registration ids are guid strings
devices_by_reg_id = dict(12=device12, 34=device34, 69=device69) # where device<id> indicates some database record
send_notification(ids, devices_by_reg_id, data)


```

Exceptions
------------
Read more on response errors [here](http://developer.android.com/guide/google/gcm/gcm.html#success)

There are two categories of errors:

GCMRetriableException # the ones you can retry
GCMNoRetryException   # the fatal ones (most)

* GCMMalformedJsonException
* GCMConnectionException
* GCMAuthenticationException
* GCMTooManyRegIdsException
* GCMNoCollapseKeyException
* GCMInvalidTtlException
* GCMMissingRegistrationException
* GCMMismatchSenderIdException
* GCMNotRegisteredException
* GCMMessageTooBigException
* GCMInvalidRegistrationException
* GCMUnavailableException

