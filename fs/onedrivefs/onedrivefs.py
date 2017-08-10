#!/usr/bin/env python3

from io import BytesIO
from itertools import chain
from pprint import pformat

from fs.base import FS
from fs.errors import DirectoryExpected, FileExpected, NoSysPath, ResourceNotFound, ResourceReadOnly
from fs.info import Info
from fs.mode import Mode
from fs.path import basename, dirname, join
from fs.subfs import SubFS
from onedrivesdk import AuthProvider, Folder, HttpProvider, Item, ItemsCollectionPage, OneDriveClient
from onedrivesdk.error import OneDriveError
from onedrivesdk.session import Session
from temp_utils.contextmanagers import temp_file

class OneDriveFS(FS):
	def __init__(self, clientId, sessionType, root="/"):
		super().__init__()
		self.root = root
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
			"read_only": True, # at least until openbin is fully implemented
			"supports_rename": False # since we don't have a syspath...
		}

	def __repr__(self):
		return f"<OneDriveFS root={self.root}>"

	def _itemInfo(self, item):
		# Looks like the dates returned are UTC
		result = Info({
			"basic": {
				"name": item.name,
				"is_dir": item.folder is not None,
			},
			"details": {
				"accessed": None, # not supported by OneDrive
				"created": item.created_date_time,
				"metadata_changed": None, # not supported by OneDrive
				"modified": item.last_modified_date_time,
				"size": item.size,
				"type": 1 if item.folder is not None else 0,
			}
		}, to_datetime=lambda x: x)
		return result

	def getinfo(self, path, namespaces=None):
		print(f"getinfo({path}, {namespaces})")
		try:
			item = self.client.item(path=join(self.root, path)).get()
		except OneDriveError as e:
			raise ResourceNotFound(path=path, exc=e)
		return self._itemInfo(item)

	def setinfo(self, path, info):
		print(f"setinfo({path}, {info})")
		itemRequest = self.client.item(path=join(self.root, path))
		for namespace in info:
			for name, value in info[namespace]:
				if namespace == "basic":
					if name == "name":
						# change name - does this include the directory?
						# how do you move an item via pyfilesystem otherwise?
						itemRequest.name = value
					elif name == "is_dir":
						# can't change this - must be an error in the framework
						assert False, "Can't change an item to and from directory"
					else:
						assert False, "Aren't we guaranteed that this is all there is in the basic namespace?"
				elif namespace == "details":
					if name == "accessed":
						pass # not supported by OneDrive
					elif name == "created":
						itemRequest.created_date_time = value
					elif name == "metadata_changed":
						pass # not supported by OneDrive
					elif name == "modified":
						itemRequest.last_modified_date_time = value
					elif name == "size":
						assert False, "Can't change item size"
					elif name == "type":
						assert False, "Can't change an item to and from directory"
					else:
						assert False, "Aren't we guaranteed that this is all there is in the details namespace?"
				else:
					# ignore namespaces that we don't recognize
					pass

	def listdir(self, path):
		print(f"listdir({path})")
		return [x.name for x in self.scandir(path)]

	def makedir(self, path, permissions=None, recreate=False):
		parentDir = dirname(path)
		itemRequest = self.client.item(path=join(self.root, parentDir))
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
		itemRequest = self.client.item(path=join(self.root, path))
		mode = Mode(mode)
		if mode.reading:
			try:
				item = itemRequest.get()
			except OneDriveError as e:
				raise ResourceNotFound(path=path, exc=e)
			with temp_file() as localPath:
				existingData = itemRequest.download(localPath)
				with open(localPath, "rb") as f:
					existingData = f.read()
			return BytesIO(existingData)
		elif mode.writing:
			raise ResourceReadOnly(path=path)
		elif mode.appending:
			raise ResourceReadOnly(path=path)
		else:
			raise ResourceReadOnly(path=path)

	def remove(self, path):
		itemRequest = self.client.item(path=join(self.root, path))
		if itemRequest.get().folder is not None:
			raise FileExpected(path=path)
		itemRequest.delete()

	def removedir(self, path):
		itemRequest = self.client.item(path=join(self.root, path))
		if itemRequest.get().folder is None:
			raise DirectoryExpected(path=path)
		itemRequest.delete()

	# non-essential method - for speeding up walk
	def scandir(self, path, namespaces=None, page=None):
		print(f"scandir({path})")
		itemRequest = self.client.item(path=join(self.root, path))
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
