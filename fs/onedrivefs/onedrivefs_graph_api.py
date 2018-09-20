#!/usr/bin/env python3

from datetime import datetime
from io import BytesIO, SEEK_END
from itertools import chain
from os import close, fdopen, remove, write
from tempfile import mkstemp

from fs.base import FS
from fs.errors import DestinationExists, DirectoryExpected, FileExists, FileExpected, ResourceNotFound, ResourceReadOnly
from fs.info import Info
from fs.iotools import RawWrapper
from fs.mode import Mode
from fs.path import basename, dirname
from fs.subfs import SubFS
from fs.time import datetime_to_epoch, epoch_to_datetime
from onedrivesdk import AuthProvider, FileSystemInfo, Folder, HttpProvider, Item, ItemReference, OneDriveClient
from onedrivesdk.error import OneDriveError
from requests_oauthlib import OAuth2Session
from temp_utils.contextmanagers import temp_file

_DRIVE_ROOT = "https://graph.microsoft.com/v1.0/me/drive/"
_ROOT_URL = _DRIVE_ROOT + "root:"

class _UploadOnClose(BytesIO):
	def __init__(self, session, path, itemId, mode):
		self.session = session
		self.path = path
		self.itemId = itemId
		self.parsedMode = mode
		buffer = bytes()
		# fileHandle, self.localPath = mkstemp(prefix="pyfilesystem-onedrive-", text=False)
		# close(fileHandle)
		if self.parsedMode.reading and not self.parsedMode.truncate:
			# TODO - check that it's a file, raise DirectoryExpected if it's not
			response = self.session.get(_ROOT_URL + path + ":/content")
			if response.status_code == 404:
				raise ResourceNotFound(path)
			buffer = response.content

		platformMode = self.parsedMode.to_platform()
		super().__init__(buffer)
		if self.parsedMode.appending:
			# seek to the end
			self.seek(0, SEEK_END)

	def close(self):
		# super().close() # close the file so that it's readable for upload
		if self.parsedMode.writing:
			# upload to OneDrive
			response = self.session.put(_DRIVE_ROOT + f"/items/{self.itemId}/content", data=self.getvalue())
			response.raise_for_status()
		remove(self.localPath)

class OneDriveFSGraphAPI(FS):
	def __init__(self, clientId, clientSecret, token, SaveToken):
		super().__init__()
		self.session = OAuth2Session(
			client_id=clientId,
			token=token,
			auto_refresh_kwargs={"client_id": clientId, "client_secret": clientSecret},
			auto_refresh_url="https://login.microsoftonline.com/consumers/oauth2/v2.0/token", # common, consumers or organizations
			token_updater=SaveToken)

		_meta = self._meta = {
			"case_insensitive": False, # I think?
			"invalid_path_chars": ":", # not sure what else
			"max_path_length": None, # don't know what the limit is
			"max_sys_path_length": None, # there's no syspath
			"network": True,
			"read_only": False, # at least until openbin is fully implemented
			"supports_rename": False # since we don't have a syspath...
		}

	def __repr__(self):
		return f"<{self.__class__.__name__}>"

	def _itemInfo(self, item): # pylint: disable=no-self-use
		dateTimeFormat = "%Y-%m-%dT%H:%M:%S.%fZ"
		# Looks like the dates returned directly in item.file_system_info (i.e. not file_system_info) are UTC naive-datetimes
		# We're supposed to return timestamps, which the framework can convert to UTC aware-datetimes
		rawInfo = {
			"basic": {
				"name": item["name"],
				"is_dir": "folder" in item,
			},
			"details": {
				"accessed": None, # not supported by OneDrive
				"created": datetime_to_epoch(datetime.strptime(item["createdDateTime"], dateTimeFormat)),
				"metadata_changed": None, # not supported by OneDrive
				"modified": datetime_to_epoch(datetime.strptime(item["lastModifiedDateTime"], dateTimeFormat)),
				"size": item["size"],
				"type": 1 if "folder" in item else 0,
			},
			"file_system_info": {
				"client_created": datetime_to_epoch(datetime.strptime(item["fileSystemInfo"]["createdDateTime"], dateTimeFormat)),
				"client_modified": datetime_to_epoch(datetime.strptime(item["fileSystemInfo"]["lastModifiedDateTime"], dateTimeFormat))
			}
		}
		if "photo" in item:
			rawInfo.update({"photo":
				{
					"camera_make": item["photo"]["cameraMake"],
					"camera_model": item["photo"]["cameraModel"],
					"exposure_denominator": item["photo"]["exposureDenominator"],
					"exposure_numerator": item["photo"]["exposureNumerator"],
					"focal_length": item["photo"]["focalLength"],
					"f_number": item["photo"]["fNumber"],
					"taken_date_time": datetime.strptime(item["photo"]["takenDateTime"], dateTimeFormat),
					"iso": item["photo"]["iso"]
				}})
		if "location" in item:
			rawInfo.update({"location":
				{
					"altitude": item["location"]["altitude"],
					"latitude": item["location"]["latitude"],
					"longitude": item["location"]["longitude"]
				}})
		if "tags" in item:
			# doesn't work
			rawInfo.update({"tags":
				{
					"tags": item["tags"]["tags"]
				}})
		return Info(rawInfo)

	def getinfo(self, path, namespaces=None):
		assert path[0] == "/"
		response = self.session.get(_ROOT_URL + path)
		if response.status_code == 404:
			raise ResourceNotFound(path=path)
		return self._itemInfo(response.json())

	def setinfo(self, path, info): # pylint: disable=too-many-branches
		itemRequest = self.client.item(path=path)
		try:
			existingItem = itemRequest.get()
		except OneDriveError as e:
			raise ResourceNotFound(path=path, exc=e)

		itemUpdate = Item()
		itemUpdate.id = existingItem.id
		itemUpdate.file_system_info = FileSystemInfo()

		for namespace in info:
			for name, value in info[namespace].items():
				if namespace == "basic":
					if name == "name":
						assert False, "Unexpected to try and change the name this way"
					elif name == "is_dir":
						# can't change this - must be an error in the framework
						assert False, "Can't change an item to and from directory"
					else:
						assert False, "Aren't we guaranteed that this is all there is in the basic namespace?"
				elif namespace == "details":
					if name == "accessed":
						pass # not supported by OneDrive
					elif name == "created":
						# incoming datetimes should be utc timestamps, OneDrive expects naive UTC datetimes
						itemUpdate.file_system_info.created_date_time = epoch_to_datetime(value).replace(tzinfo=None)
					elif name == "metadata_changed":
						pass # not supported by OneDrive
					elif name == "modified":
						# incoming datetimes should be utc timestamps, OneDrive expects naive UTC datetimes
						itemUpdate.file_system_info.last_modified_date_time = epoch_to_datetime(value).replace(tzinfo=None)
					elif name == "size":
						assert False, "Can't change item size"
					elif name == "type":
						assert False, "Can't change an item to and from directory"
					else:
						assert False, "Aren't we guaranteed that this is all there is in the details namespace?"
				else:
					# ignore namespaces that we don't recognize
					pass
		itemRequest.update(itemUpdate)

	def listdir(self, path):
		return [x.name for x in self.scandir(path)]

	def makedir(self, path, permissions=None, recreate=False):
		parentDir = dirname(path)
		# parentDir here is expected to have a leading slash
		assert parentDir[0] == "/"
		response = self.session.get(_ROOT_URL + parentDir)
		response.raise_for_status()
		# itemRequest = self.client.item(path=parentDir)
		# try:
		# 	item = itemRequest.get()
		# except OneDriveError as e:
		# 	raise ResourceNotFound(path=parentDir, exc=e)

		# if item.folder is None:
		# 	raise DirectoryExpected(path=parentDir)

		response = self.session.post(_ROOT_URL + parentDir + ":/children",
			json={"name": basename(path), "folder": {}})
		# TODO - will need to deal with these errors locally but don't know what they are yet
		response.raise_for_status()
		# newItem = Item()
		# newItem.name = basename(path)
		# newItem.folder = Folder()
		# itemRequest.children.add(entity=newItem)
		# don't need to close this filesystem so we return the non-closing version
		return SubFS(self, path)

	def openbin(self, path, mode="r", buffering=-1, **options):
		parsedMode = Mode(mode)
		exists = self.exists(path)
		if parsedMode.exclusive and exists:
			raise FileExists(path)
		elif parsedMode.reading and not parsedMode.create and not exists:
			raise ResourceNotFound(path)
		elif self.isdir(path):
			raise FileExpected(path)
		itemId = None
		if exists:
			response = self.session.get(_ROOT_URL + path)
			response.raise_for_status()
			itemId = response["id"]
		return _UploadOnClose(client=self.session, path=path, itemId=itemId, mode=parsedMode)

	def remove(self, path):
		itemRequest = self.client.item(path=path)
		if itemRequest.get().folder is not None:
			raise FileExpected(path=path)
		itemRequest.delete()

	def removedir(self, path):
		# need to get the item id for this path
		response = self.session.get(_ROOT_URL + path)
		if response.status_code == 404:
			raise ResourceNotFound(path)
		# TODO - check that it's a directory, raise DirectoryExpected if it's not
		itemId = response.json()["id"] # let JSON parsing exceptions propagate for now
		response = self.session.delete(_DRIVE_ROOT + f"items/{itemId}")
		assert response.status_code == 204, itemId # this is according to the spec

	# non-essential method - for speeding up walk
	def scandir(self, path, namespaces=None, page=None):
		response = self.session.get(_ROOT_URL + path) # assumes path is the full path, starting with "/"
		if response.code == 404:
			raise ResourceNotFound(path=path)
		if "folder" not in response.json():
			raise DirectoryExpected(path=path)
		response = self.session.get(_ROOT_URL + path + ":/children") # assumes path is the full path, starting with "/"
		if response.code == 404:
			raise ResourceNotFound(path=path)
		parsedResult = result.json()
		assert "@odata.context" in parsedResult
		ret = (self._itemInfo(x) for x in result["value"])
		return ret
		# for child in result["value"]:

		# itemRequest = self.client.item(path=path)
		# try:
		# 	item = itemRequest.get()
		# except OneDriveError as e:
		# 	raise ResourceNotFound(path=path, exc=e)
		# if item.folder is None:
		# 	raise DirectoryExpected(path=path)

		# childrenRequest = itemRequest.children.request()
		# children = childrenRequest.get()
		# result = (self._itemInfo(x) for x in children)

		# while hasattr(children, "_next_page_link"):
		# 	childrenRequest = childrenRequest.get_next_page_request(children, self.client)
		# 	children = childrenRequest.get()
		# 	result = chain(result, (self._itemInfo(x) for x in children))

		# return result

	def move(self, src_path, dst_path, overwrite=False):
		if not overwrite and self.exists(dst_path):
			raise DestinationExists(dst_path)
		srcRequest = self.client.item(path=src_path)

		itemUpdate = Item()

		newFilename = basename(dst_path)
		if not self.isdir(dst_path) and newFilename != basename(src_path):
			itemUpdate.name = newFilename

		parentDir = dirname(dst_path)
		if parentDir != dirname(src_path):
			try:
				parentDirItem = self.client.item(path=parentDir).get()
			except OneDriveError as e:
				raise ResourceNotFound(path=parentDir, exc=e)

			ref = ItemReference()
			ref.id = parentDirItem.id
			itemUpdate.parent_reference = ref

		srcRequest.update(itemUpdate)
