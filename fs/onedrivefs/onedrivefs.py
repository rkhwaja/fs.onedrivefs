#!/usr/bin/env python3

from io import SEEK_END
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
from temp_utils.contextmanagers import temp_file

# onedrivesdk only uploads from a file path
class UploadOnClose(RawWrapper):
	def __init__(self, client, path, mode):
		self.client = client
		self.path = path
		self.parsedMode = mode
		fileHandle, self.localPath = mkstemp(prefix="pyfilesystem-onedrive-", text=False)
		close(fileHandle)
		if self.parsedMode.reading and not self.parsedMode.truncate:
			try:
				self.client.item(path=path).download(self.localPath)
			except OneDriveError as e:
				pass
		super().__init__(f=open(self.localPath, mode=self.parsedMode.to_platform() + "b"))
		if self.parsedMode.appending:
			# seek to the end
			self.seek(0, SEEK_END)

	def close(self):
		super().close() # close the file so that it's readable for upload
		if self.parsedMode.writing:
			# upload to OneDrive
			self.client.item(path=self.path).upload(self.localPath)
		remove(self.localPath)

class OneDriveFS(FS):
	def __init__(self, clientId, sessionType):
		super().__init__()
		httpProvider = HttpProvider()
		authProvider = AuthProvider(http_provider=httpProvider, client_id=clientId, scopes=["wl.signin", "wl.offline_access", "onedrive.readwrite"], session_type=sessionType)
		self.client = OneDriveClient("https://api.onedrive.com/v1.0/", authProvider, httpProvider)
		self.client.auth_provider.load_session()

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
		return f"<OneDriveFS>"

	def _itemInfo(self, item): # pylint: disable=no-self-use
		# Looks like the dates returned directly in item.file_system_info (i.e. not file_system_info) are UTC naive-datetimes
		# We're supposed to return timestamps, which the framework can convert to UTC aware-datetimes
		rawInfo = {
			"basic": {
				"name": item.name,
				"is_dir": item.folder is not None,
			},
			"details": {
				"accessed": None, # not supported by OneDrive
				"created": datetime_to_epoch(item.created_date_time),
				"metadata_changed": None, # not supported by OneDrive
				"modified": datetime_to_epoch(item.last_modified_date_time),
				"size": item.size,
				"type": 1 if item.folder is not None else 0,
			},
			"file_system_info": {
				"client_created": datetime_to_epoch(item.file_system_info.created_date_time),
				"client_modified": datetime_to_epoch(item.file_system_info.last_modified_date_time)
			}
		}
		if item.photo is not None:
			rawInfo.update({"photo":
				{
					"camera_make": item.photo.camera_make,
					"camera_model": item.photo.camera_model,
					"exposure_denominator": item.photo.exposure_denominator,
					"exposure_numerator": item.photo.exposure_numerator,
					"focal_length": item.photo.focal_length,
					"f_number": item.photo.f_number,
					"taken_date_time": item.photo.taken_date_time,
					"iso": item.photo.iso
				}})
		if item.location is not None:
			rawInfo.update({"location":
				{
					"altitude": item.location.altitude,
					"latitude": item.location.latitude,
					"longitude": item.location.longitude
				}})
		if item.tags is not None:
			rawInfo.update({"tags":
				{
					"tags": list(item.tags.tags)
				}})
		return Info(rawInfo)

	def getinfo(self, path, namespaces=None):
		try:
			item = self.client.item(path=path).get()
		except OneDriveError as e:
			raise ResourceNotFound(path=path, exc=e)
		return self._itemInfo(item)

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
		itemRequest = self.client.item(path=parentDir)
		try:
			item = itemRequest.get()
		except OneDriveError as e:
			raise ResourceNotFound(path=parentDir, exc=e)

		if item.folder is None:
			raise DirectoryExpected(path=parentDir)
		newItem = Item()
		newItem.name = basename(path)
		newItem.folder = Folder()
		itemRequest.children.add(entity=newItem)
		# don't need to close this filesystem so we return the non-closing version
		return SubFS(self, path)

	def openbin(self, path, mode="r", buffering=-1, **options):
		parsedMode = Mode(mode)
		if parsedMode.exclusive and self.exists(path):
			raise FileExists(path)
		elif parsedMode.reading and not parsedMode.create and not self.exists(path):
			raise ResourceNotFound(path)
		elif self.isdir(path):
			raise FileExpected(path)
		return UploadOnClose(client=self.client, path=path, mode=parsedMode)

	def remove(self, path):
		itemRequest = self.client.item(path=path)
		if itemRequest.get().folder is not None:
			raise FileExpected(path=path)
		itemRequest.delete()

	def removedir(self, path):
		itemRequest = self.client.item(path=path)
		if itemRequest.get().folder is None:
			raise DirectoryExpected(path=path)
		itemRequest.delete()

	# non-essential method - for speeding up walk
	def scandir(self, path, namespaces=None, page=None):
		itemRequest = self.client.item(path=path)
		try:
			item = itemRequest.get()
		except OneDriveError as e:
			raise ResourceNotFound(path=path, exc=e)
		if item.folder is None:
			raise DirectoryExpected(path=path)

		childrenRequest = itemRequest.children.request()
		children = childrenRequest.get()
		result = (self._itemInfo(x) for x in children)

		while hasattr(children, "_next_page_link"):
			childrenRequest = childrenRequest.get_next_page_request(children, self.client)
			children = childrenRequest.get()
			result = chain(result, (self._itemInfo(x) for x in children))

		return result

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
