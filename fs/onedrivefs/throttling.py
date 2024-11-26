from functools import wraps
from logging import getLogger
from time import sleep

from requests import codes

_log = getLogger(__name__)

def throttle():
	def decorator(func):
		@wraps(func)
		def wrapper(*args, **kwargs):
			while True:
				resp = func(*args, **kwargs)
				if resp.status_code != codes.too_many_requests:
					break
				# look at the response and retry after a delay
				retryAfterSeconds = int(resp.headers['Retry-After'])
				_log.info(f'Sleeping for {retryAfterSeconds} sec after throttling')
				sleep(retryAfterSeconds)
			return resp
		return wrapper
	return decorator
