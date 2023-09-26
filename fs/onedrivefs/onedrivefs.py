from datetime import datetime, timezone
from io import BytesIO
from logging import getLogger
from urllib.parse import urlencode

from fs.base import FS
from fs.enums import ResourceType
from fs.errors import DestinationExists, DirectoryExists, DirectoryExpected, DirectoryNotEmpty, FileExists, FileExpected, ResourceNotFound
from fs.info import Info
from fs.mode import Mode
from fs.path import basename, dirname
from fs.subfs import SubFS
from fs.time import datetime_to_epoch, epoch_to_datetime
from requests import codes, get
from requests_oauthlib import OAuth2Session

_log = getLogger(__name__)

SIMPLE_UPLOAD_LIMIT = 4e6

def _ParseDateTime(dt):
	try:
		return datetime.strptime(dt, '%Y-%m-%dT%H:%M:%S.%fZ')
	except ValueError:
		return datetime.strptime(dt, '%Y-%m-%dT%H:%M:%SZ')

def _FormatDateTime(dt):
	return dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat() + 'Z'

def _UpdateDict(dict_, sourceKey, targetKey, processFn=None):
	if sourceKey in dict_:
		return {targetKey: processFn(dict_[sourceKey]) if processFn is not None else dict_[sourceKey]}
	return {}

def _HandleError(response):
	# https://docs.microsoft.com/en-us/onedrive/developer/rest-api/concepts/errors
	if response.ok is False:
		_log.error(f'Response text: {response.text}')
	response.raise_for_status()

class _UploadOnClose(BytesIO):
	def __init__(self, session, path, itemId, mode):
		self.session = session
		self.path = path
		self.itemId = itemId
		self.parsedMode = mode
		initialData = None
		if (self.parsedMode.appending or self.parsedMode.reading) and not self.parsedMode.truncate:
			response = self.session.get_path(path, '/content')
			assert response.status_code != codes.partial, 'Partial content response'
			if response.status_code == codes.not_found:
				if not self.parsedMode.appending:
					raise ResourceNotFound(path)
			else:
				response.raise_for_status()
				initialData = response.content

		super().__init__(initialData)
		if self.parsedMode.appending and initialData is not None:
			# seek to the end
			self.seek(len(initialData))
		self._closed = False

	def truncate(self, size=None):
		# BytesIO.truncate works as needed except if truncating to longer than the existing size
		originalSize = len(self.getvalue())
		super().truncate(size)
		if size is None: # Bytes.truncate works fine for this case
			return len(self.getvalue())
		if size <= originalSize: # BytesIO.truncate works fine for this case
			return len(self.getvalue())
		# this is the behavior of native files and is specified by pyfilesystem2
		self.write(b'\0' * (size - originalSize))
		self.seek(originalSize)
		return len(self.getvalue())

	def read(self, size=-1):
		if self.parsedMode.reading is False:
			raise OSError('This file object is not readable')
		return super().read(size)

	def write(self, data):
		if self.parsedMode.writing is False:
			raise OSError('This file object is not writable')
		return super().write(data)

	def readable(self):
		return self.parsedMode.reading

	def writable(self):
		return self.parsedMode.writing

	@property
	def closed(self):
		return self._closed

	@property
	def mode(self):
		return self.parsedMode.to_platform_bin()

	def _ResumableUpload(self, itemId, filename):
		uploadInfo = self.session.post_item(itemId, f':/{filename}:/createUploadSession')
		uploadInfo.raise_for_status()
		uploadUrl = uploadInfo.json()['uploadUrl']
		size = len(self.getvalue())
		bytesSent = 0
		while bytesSent < size:
			# data size should be a multiple of 320 KiB
			length = min(320 * 1024, size - bytesSent)
			dataToSend = self.getvalue()[bytesSent:bytesSent + length]
			assert len(dataToSend) == length
			headers = {'content-range': f'bytes {bytesSent}-{bytesSent + length - 1}/{size}'}
			response = self.session.put(uploadUrl, data=dataToSend, headers=headers)
			if response.status_code == codes.conflict:
				_log.warning(f'Retrying upload due to {response}')
				response = self.session.put(uploadUrl, data=dataToSend, headers=headers)
			response.raise_for_status()
			bytesSent += length

	def close(self):
		if self.parsedMode.writing:
			response = self.session.get_path(dirname(self.path))
			response.raise_for_status()
			parentId = response.json()['id']
			filename = basename(self.path)
			if self.itemId is None:
				# we have to create a new file
				if len(self.getvalue()) < SIMPLE_UPLOAD_LIMIT:
					response = self.session.put_item(parentId, f':/{filename}:/content', data=self.getvalue())
					response.raise_for_status()
				else:
					self._ResumableUpload(parentId, filename)
			elif len(self.getvalue()) < SIMPLE_UPLOAD_LIMIT: # upload a new version
				response = self.session.put_item(self.itemId, '/content', data=self.getvalue())
				# workaround for possible OneDrive bug
				if response.status_code == codes.conflict:
					_log.warning(f'Retrying upload due to {response}')
					response = self.session.put_item(self.itemId, '/content', data=self.getvalue())
				response.raise_for_status()
			else:
				self._ResumableUpload(parentId, filename)
		self._closed = True

class SubOneDriveFS(SubFS):
	def download_as_format(self, path, output_file, format, **options): # noqa: A002
		fs, pathDelegate = self.delegate_path(path)
		return fs.download_as_format(pathDelegate, output_file, format, **options)

	def create_subscription(self, notification_url, expiration_date_time, client_state):
		return self.delegate_fs().create_subscription(notification_url, expiration_date_time, client_state)

	def delete_subscription(self, id_):
		return self.delegate_fs().delete_subscription(id_)

	def update_subscription(self, id_, expiration_date_time):
		return self.delegate_fs().update_subscription(id_, expiration_date_time)

class OneDriveSession(OAuth2Session):
	def __init__(self, *args, drive_root, **kwargs):
		self._drive_root = drive_root
		super().__init__(*args, **kwargs)

	def path_url(self, path, extra):
		# the path must start with '/'
		if path in {'/', ''}: # special handling for the root directory
			return f'{self._drive_root}/root{extra}'
		if extra != '':
			extra = ':' + extra
		return f'{self._drive_root}/root:{path}{extra}'

	def item_url(self, itemId, extra):
		return f'{self._drive_root}/items/{itemId}{extra}'

	def get_path(self, path, extra='', **kwargs):
		return self.get(self.path_url(path, extra), **kwargs)

	def post_path(self, path, extra='', **kwargs):
		return self.post(self.path_url(path, extra), **kwargs)

	def delete_path(self, path, extra='', **kwargs):
		return self.delete(self.path_url(path, extra), **kwargs)

	def get_item(self, path, extra='', **kwargs):
		return self.get(self.item_url(path, extra), **kwargs)

	def patch_item(self, path, extra='', **kwargs):
		return self.patch(self.item_url(path, extra), **kwargs)

	def post_item(self, path, extra='', **kwargs):
		return self.post(self.item_url(path, extra), **kwargs)

	def put_item(self, path, extra='', **kwargs):
		return self.put(self.item_url(path, extra), **kwargs)

	def delete_item(self, path, extra='', **kwargs):
		return self.delete(self.item_url(path, extra), **kwargs)

class OneDriveFS(FS):
	subfs_class = SubOneDriveFS
	_service_root = 'https://graph.microsoft.com/v1.0'

	def __init__(self, clientId, clientSecret, token, SaveToken, tenant='consumers', **kwargs):
		super().__init__()

		self.set_drive(**kwargs)
		auto_refresh_kwargs = {'client_id': clientId}
		if clientSecret is not None:
			auto_refresh_kwargs['client_secret'] = clientSecret
		self.session = OneDriveSession(
			client_id=clientId,
			token=token,
			auto_refresh_kwargs=auto_refresh_kwargs,
			auto_refresh_url=f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token',
			token_updater=SaveToken,
			drive_root=self._drive_root
		)

		self._meta = {
			'case_insensitive': True,
			'invalid_path_chars': ':\0\\',
			'max_path_length': None, # don't know what the limit is
			'max_sys_path_length': None, # there's no syspath
			'network': True,
			'read_only': False,
			'supports_rename': False # since we don't have a syspath...
		}

	def __repr__(self):
		return f'<{self.__class__.__name__}>'

	def set_drive(self, driveId=None, userId=None, groupId=None, siteId=None):
		with self._lock:
			if sum(bool(x) for x in (driveId, userId, groupId, siteId)) > 1:
				raise ValueError('Only one of driveId, userId, groupId, or siteId can be specified at a time')

			# Documentation for the MS Graph File API here:
			# https://docs.microsoft.com/en-us/graph/api/resources/onedrive
			if driveId:
				self._resource_root = f'drives/{driveId}'        # a specific drive ID
			elif userId:
				self._resource_root = f'users/{userId}/drive'    # a specific user's drive
			elif groupId:
				self._resource_root = f'groups/{groupId}/drive'  # default document library of a specific group
			elif siteId:
				self._resource_root = f'sites/{siteId}/drive'    # default document library of a SharePoint site
			else:
				self._resource_root = 'me/drive'                 # default - the logged in user's drive

			_log.debug(f'Drive set to {self._resource_root}')

			self._drive_root = f'{self._service_root}/{self._resource_root}'

	def download_as_format(self, path, output_file, format, **options): # noqa: A002
		_log.info(f'download_as_format({path}, {output_file}, {format}, {options})')
		with self._lock:
			path = self.validatepath(path)
			# validate per-format arguments
			if format == 'jpg' and ('width' not in options or 'height' not in options or not isinstance(options['width'], int) or not isinstance(options['height'], int)):
				raise ValueError('Format jpg requires integer width and height arguments')
			options['format'] = format
			optionsString = urlencode(options)
			response = self.session.get_path(path, f'/content?{optionsString}')
			assert response.status_code != codes.partial, 'Partial content response'
			if response.status_code == codes.not_found:
				raise ResourceNotFound(path)
			response.raise_for_status()

			output_file.write(response.content)

	def create_subscription(self, notification_url, expiration_date_time, client_state):
		_log.info(f'create_subscription({notification_url}, {expiration_date_time}, {client_state})')
		with self._lock:
			payload = {
				'changeType': 'updated', # OneDrive only supports updated
				'notificationUrl': notification_url,
				'resource': f'/{self._resource_root}/root',
				'expirationDateTime': _FormatDateTime(expiration_date_time),
				'clientState': client_state
			}
			response = self.session.post(f'{self._service_root}/subscriptions', json=payload)
			_HandleError(response) # this is backup, if actual errors are thrown from here we should respond to them individually, e.g. if validation fails
			assert response.status_code == codes.created, 'Expected 201 Created response'
			subscription = response.json()
			assert subscription['changeType'] == payload['changeType']
			assert subscription['notificationUrl'] == payload['notificationUrl']
			assert subscription['resource'] == payload['resource']
			assert 'expirationDateTime' in subscription
			assert subscription['clientState'] == payload['clientState']
			_log.debug(f'Subscription created successfully: {subscription}')
			return subscription['id']

	def delete_subscription(self, id_):
		_log.info(f'delete_subscription({id_})')
		with self._lock:
			response = self.session.delete(f'{self._service_root}/subscriptions/{id_}')
			response.raise_for_status() # this is backup, if actual errors are thrown from here we should respond to them individually, e.g. if validation fails
			assert response.status_code == codes.no_content, 'Expected 204 No content'

	def update_subscription(self, id_, expiration_date_time):
		_log.info(f'update_subscription({id_}, {expiration_date_time})')
		with self._lock:
			response = self.session.patch(f'{self._service_root}/subscriptions/{id_}', json={'expirationDateTime': _FormatDateTime(expiration_date_time)})
			response.raise_for_status() # this is backup, if actual errors are thrown from here we should respond to them individually, e.g. if validation fails
			assert response.status_code == codes.ok, 'Expected 200 OK'
			subscription = response.json()
			assert subscription['id'] == id_
			assert 'expirationDateTime' in subscription

	# Translates OneDrive DriveItem dictionary to an fs Info object
	def _itemInfo(self, item):
		# Looks like the dates returned directly in item.file_system_info (i.e. not file_system_info) are UTC naive-datetimes
		# We're supposed to return timestamps, which the framework can convert to UTC aware-datetimes
		rawInfo = {
			'basic': {
				'name': item['name'],
				'is_dir': 'folder' in item,
			},
			'details': {
				'accessed': None, # not supported by OneDrive
				'created': datetime_to_epoch(_ParseDateTime(item['createdDateTime'])),
				'metadata_changed': None, # not supported by OneDrive
				'modified': datetime_to_epoch(_ParseDateTime(item['lastModifiedDateTime'])),
				'size': item['size'],
				'type': ResourceType.directory if 'folder' in item else ResourceType.file,
			},
			'file_system_info': {
				'client_created': datetime_to_epoch(_ParseDateTime(item['fileSystemInfo']['createdDateTime'])),
				'client_modified': datetime_to_epoch(_ParseDateTime(item['fileSystemInfo']['lastModifiedDateTime']))
			}
		}
		if 'photo' in item:
			rawInfo['photo'] = {}
			rawInfo['photo'].update(_UpdateDict(item['photo'], 'cameraMake', 'camera_make'))
			rawInfo['photo'].update(_UpdateDict(item['photo'], 'cameraModel', 'camera_model'))
			rawInfo['photo'].update(_UpdateDict(item['photo'], 'exposureDenominator', 'exposure_denominator'))
			rawInfo['photo'].update(_UpdateDict(item['photo'], 'exposureNumerator', 'exposure_numerator'))
			rawInfo['photo'].update(_UpdateDict(item['photo'], 'focalLength', 'focal_length'))
			rawInfo['photo'].update(_UpdateDict(item['photo'], 'fNumber', 'f_number'))
			rawInfo['photo'].update(_UpdateDict(item['photo'], 'takenDateTime', 'taken_date_time', _ParseDateTime))
			rawInfo['photo'].update(_UpdateDict(item['photo'], 'iso', 'iso'))
		if 'image' in item:
			rawInfo['image'] = {}
			rawInfo['image'].update(_UpdateDict(item['image'], 'width', 'width'))
			rawInfo['image'].update(_UpdateDict(item['image'], 'height', 'height'))
		if 'location' in item:
			rawInfo['location'] = {}
			rawInfo['location'].update(_UpdateDict(item['location'], 'altitude', 'altitude'))
			rawInfo['location'].update(_UpdateDict(item['location'], 'latitude', 'latitude'))
			rawInfo['location'].update(_UpdateDict(item['location'], 'longitude', 'longitude'))
		if 'file' in item and 'hashes' in item['file']:
			rawInfo['hashes'] = {}
			# The spec is at https://docs.microsoft.com/en-us/onedrive/developer/rest-api/resources/hashes
			# CRC32 appears in the spec but not in the implementation
			rawInfo['hashes'].update(_UpdateDict(item['file']['hashes'], 'crc32Hash', 'CRC32'))
			# Standard SHA1
			rawInfo['hashes'].update(_UpdateDict(item['file']['hashes'], 'sha1Hash', 'SHA1'))
			# proprietary hash for change detection
			rawInfo['hashes'].update(_UpdateDict(item['file']['hashes'], 'quickXorHash', 'quickXorHash'))
		if 'tags' in item:
			# doesn't work
			rawInfo.update({'tags':
				{
					'tags': item['tags']['tags']
				}})
		return Info(rawInfo)

	def getinfo(self, path, namespaces=None):
		_log.info(f'getinfo({path}, {namespaces})')
		path = self.validatepath(path)
		with self._lock:
			response = self.session.get_path(path)
			if response.status_code == codes.not_found:
				raise ResourceNotFound(path=path)
			response.raise_for_status()
			return self._itemInfo(response.json())

	def setinfo(self, path, info): # noqa: C901
		_log.info(f'setinfo({path}, {info})')
		def to_datetime(value):
			return epoch_to_datetime(value).replace(tzinfo=None).isoformat() + 'Z'

		path = self.validatepath(path)
		with self._lock:
			response = self.session.get_path(path)
			if response.status_code == codes.not_found:
				raise ResourceNotFound(path=path)
			existingItem = response.json()
			updatedData = {}

			for namespace in info:
				for name, value in info[namespace].items():
					if namespace == 'basic':
						if name == 'name':
							assert False, 'Unexpected to try and change the name this way'
						elif name == 'is_dir':
							# can't change this - must be an error in the framework
							assert False, "Can't change an item to and from directory"
						else:
							assert False, "Aren't we guaranteed that this is all there is in the basic namespace?"
					elif namespace == 'details':
						if name == 'accessed':
							pass # not supported by OneDrive
						elif name == 'created':
							# incoming datetimes should be utc timestamps, OneDrive expects naive UTC datetimes
							if 'fileSystemInfo' not in updatedData:
								updatedData['fileSystemInfo'] = {}
							updatedData['fileSystemInfo']['createdDateTime'] = to_datetime(value)
						elif name == 'metadata_changed':
							pass # not supported by OneDrive
						elif name == 'modified':
							# incoming datetimes should be utc timestamps, OneDrive expects naive UTC datetimes
							if 'fileSystemInfo' not in updatedData:
								updatedData['fileSystemInfo'] = {}
							updatedData['fileSystemInfo']['lastModifiedDateTime'] = to_datetime(value)
						elif name == 'size':
							assert False, "Can't change item size"
						elif name == 'type':
							assert False, "Can't change an item to and from directory"
						else:
							assert False, "Aren't we guaranteed that this is all there is in the details namespace?"
					else:
						# ignore namespaces that we don't recognize
						pass
			response = self.session.patch_item(existingItem['id'], json=updatedData)
			response.raise_for_status()

	def listdir(self, path):
		_log.info(f'listdir({path})')
		path = self.validatepath(path)
		with self._lock:
			return [x.name for x in self.scandir(path)]

	def makedir(self, path, permissions=None, recreate=False):
		_log.info(f'makedir({path}, {permissions}, {recreate})')
		path = self.validatepath(path)
		with self._lock:
			parentDir = dirname(path)
			# parentDir here is expected to have a leading slash
			assert parentDir[0] == '/'
			response = self.session.get_path(parentDir)
			if response.status_code == codes.not_found:
				raise ResourceNotFound(parentDir)
			response.raise_for_status()

			if recreate is False:
				response = self.session.get_path(path)
				if response.status_code != codes.not_found:
					raise DirectoryExists(path)

			response = self.session.post_path(parentDir, '/children',
				json={'name': basename(path), 'folder': {}})
			# TODO - will need to deal with these errors locally but don't know what they are yet
			response.raise_for_status()
			# don't need to close this filesystem so we return the non-closing version
			return SubFS(self, path)

	def openbin(self, path, mode='r', buffering=-1, **options):
		_log.info(f'openbin({path}, {mode}, {buffering}, {options})')
		path = self.validatepath(path)
		with self._lock:
			if 't' in mode:
				raise ValueError('Text mode is not allowed in openbin')
			parsedMode = Mode(mode)
			exists = self.exists(path)
			if parsedMode.exclusive and exists:
				raise FileExists(path)
			if parsedMode.reading and not parsedMode.create and not exists:
				raise ResourceNotFound(path)
			if self.isdir(path):
				raise FileExpected(path)
			if parsedMode.writing:
				# make sure that the parent directory exists
				parentDir = dirname(path)
				response = self.session.get_path(parentDir)
				if response.status_code == codes.not_found:
					raise ResourceNotFound(parentDir)
				response.raise_for_status()
			itemId = None
			if exists:
				response = self.session.get_path(path)
				response.raise_for_status()
				itemId = response.json()['id']
			return _UploadOnClose(session=self.session, path=path, itemId=itemId, mode=parsedMode)

	def remove(self, path):
		_log.info(f'remove({path})')
		path = self.validatepath(path)
		with self._lock:
			response = self.session.get_path(path)
			if response.status_code == codes.not_found:
				raise ResourceNotFound(path)
			response.raise_for_status()
			itemData = response.json()
			if 'folder' in itemData:
				raise FileExpected(path=path)
			response = self.session.delete_path(path)
			response.raise_for_status()

	def removedir(self, path):
		_log.info(f'removedir({path})')
		path = self.validatepath(path)
		with self._lock:
			# need to get the item id for this path
			response = self.session.get_path(path)
			if response.status_code == codes.not_found:
				raise ResourceNotFound(path)
			itemData = response.json()
			if 'folder' not in itemData:
				raise DirectoryExpected(path)

			response = self.session.get_path(path, '/children')
			response.raise_for_status()
			childrenData = response.json()
			if len(childrenData['value']) > 0:
				raise DirectoryNotEmpty(path)

			itemId = itemData['id'] # let JSON parsing exceptions propagate for now
			response = self.session.delete_item(itemId)
			assert response.status_code == codes.no_content, itemId # this is according to the spec

	# non-essential method - for speeding up walk
	def scandir(self, path, namespaces=None, page=None):
		_log.info(f'scandir({path}, {namespaces}, {page})')
		path = self.validatepath(path)
		with self._lock:
			response = self.session.get_path(path) # assumes path is the full path, starting with "/"
			if response.status_code == codes.not_found:
				raise ResourceNotFound(path=path)
			if 'folder' not in response.json():
				_log.debug(f'{response.json()}')
				raise DirectoryExpected(path=path)
			result = []
			nextLink = self.session.path_url(path, '/children') # assumes path is the full path, starting with "/"
			while nextLink:
				response = self.session.get(nextLink)
				if response.status_code == codes.not_found:
					raise ResourceNotFound(path=path)
				parsedResult = response.json()
				assert '@odata.context' in parsedResult
				result.extend([self._itemInfo(item) for item in parsedResult['value']])
				if page is not None and page[1] <= len(result):
					return result[page[0]: page[1]]
				nextLink = parsedResult.get('@odata.nextLink')
			if page is not None:
				return result[page[0]: page[1]]
			return result

	def move(self, src_path, dst_path, overwrite=False, preserve_time=False):
		_log.info(f'move({src_path}, {dst_path}, {overwrite}, {preserve_time})')
		src_path = self.validatepath(src_path)
		dst_path = self.validatepath(dst_path)
		with self._lock:
			if not overwrite and self.exists(dst_path):
				raise DestinationExists(dst_path)
			driveItemResponse = self.session.get_path(src_path)
			if driveItemResponse.status_code == codes.not_found:
				raise ResourceNotFound(src_path)
			driveItemResponse.raise_for_status()
			driveItem = driveItemResponse.json()

			if 'folder' in driveItem:
				raise FileExpected(src_path)

			itemUpdate = {}

			newFilename = basename(dst_path)
			if not self.isdir(dst_path) and newFilename != basename(src_path):
				itemUpdate['name'] = newFilename

			parentDir = dirname(dst_path)
			if parentDir != dirname(src_path):
				parentDirItem = self.session.get_path(parentDir)
				if parentDirItem.status_code == codes.not_found:
					raise ResourceNotFound(parentDir)
				parentDirItem.raise_for_status()
				itemUpdate['parentReference'] = {'id': parentDirItem.json()['id']}

			itemId = driveItem['id']
			response = self.session.patch_item(itemId, json=itemUpdate)
			if response.status_code == codes.conflict and overwrite is True:
				# delete the existing version and then try again
				response = self.session.delete_path(dst_path)
				response.raise_for_status()

				# try again
				response = self.session.patch_item(itemId, json=itemUpdate)
				response.raise_for_status()
				return
			if response.status_code == codes.conflict and overwrite is False:
				_log.debug("Retrying move in case it's an erroneous error (see issue #7)")
				response = self.session.patch_item(itemId, json=itemUpdate)
				response.raise_for_status()
				return
			response.raise_for_status()

	def copy(self, src_path, dst_path, overwrite=False, preserve_time=False):
		_log.info(f'copy({src_path}, {dst_path}, {overwrite}, {preserve_time})')
		src_path = self.validatepath(src_path)
		dst_path = self.validatepath(dst_path)
		with self._lock:
			if not overwrite and self.exists(dst_path):
				raise DestinationExists(dst_path)

			driveItemResponse = self.session.get_path(src_path)
			if driveItemResponse.status_code == codes.not_found:
				raise ResourceNotFound(src_path)
			driveItemResponse.raise_for_status()
			driveItem = driveItemResponse.json()

			if 'folder' in driveItem:
				raise FileExpected(src_path)

			newParentDir = dirname(dst_path)
			newFilename = basename(dst_path)

			parentDirResponse = self.session.get_path(newParentDir)
			if parentDirResponse.status_code == codes.not_found:
				raise ResourceNotFound(src_path)
			parentDirResponse.raise_for_status()
			parentDirItem = parentDirResponse.json()

			# This just asynchronously starts the copy
			response = self.session.post_item(driveItem['id'], '/copy', json={
				'parentReference': {'driveId': parentDirItem['parentReference']['driveId'], 'id': parentDirItem['id']},
				'name': newFilename
			})
			response.raise_for_status()
			assert response.status_code == codes.accepted, 'Response code should be 202 (Accepted)'
			monitorUri = response.headers['Location']
			while True:
				# monitor uris don't require authentication
				# (https://docs.microsoft.com/en-us/onedrive/developer/rest-api/concepts/long-running-actions)
				jobStatusResponse = get(monitorUri) # noqa: S113
				jobStatusResponse.raise_for_status()
				jobStatus = jobStatusResponse.json()
				if jobStatus['operation'] != 'itemCopy' or jobStatus['status'] not in ['inProgress', 'completed', 'notStarted']:
					_log.warning(f'Unexpected status: {jobStatus}')
				if jobStatus['status'] == 'completed':
					break
