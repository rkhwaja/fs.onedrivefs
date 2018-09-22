#!/usr/bin/env python3

from datetime import datetime
from io import BytesIO, SEEK_END
from logging import info

from fs.base import FS
from fs.enums import ResourceType
from fs.errors import DestinationExists, DirectoryExists, DirectoryExpected, DirectoryNotEmpty, FileExists, FileExpected, ResourceNotFound, ResourceReadOnly
from fs.info import Info
from fs.iotools import RawWrapper
from fs.mode import Mode
from fs.path import basename, dirname
from fs.subfs import SubFS
from fs.time import datetime_to_epoch, epoch_to_datetime
from requests_oauthlib import OAuth2Session

_DRIVE_ROOT = "https://graph.microsoft.com/v1.0/me/drive/"

def _ItemUrl(itemId, extra):
	return f"{_DRIVE_ROOT}items/{itemId}{extra}"

def _PathUrl(path, extra):
	return f"{_DRIVE_ROOT}root:{path}{extra}"

def _ParseDateTime(dt):
	try:
		return datetime.strptime(dt, "%Y-%m-%dT%H:%M:%S.%fZ")
	except ValueError:
		return datetime.strptime(dt, "%Y-%m-%dT%H:%M:%SZ")

class _UploadOnClose(BytesIO):
	def __init__(self, session, path, itemId, mode):
		info(f"_UploadOnClose.__init__ {path}, {mode}")
		self.session = session
		self.path = path
		self.itemId = itemId
		self.parsedMode = mode
		buffer = bytes()
		if (self.parsedMode.appending or self.parsedMode.reading) and not self.parsedMode.truncate:
			# TODO - check that it's a file, raise DirectoryExpected if it's not
			response = self.session.get(_PathUrl(path, ":/content"))
			if response.status_code == 404:
				if not self.parsedMode.appending:
					raise ResourceNotFound(path)
			else:
				info("Read existing file content from url")
				buffer = response.content

		super().__init__(buffer)
		if self.parsedMode.appending:
			# seek to the end
			self.seek(0, SEEK_END)
		self._closed = False

	def read(self, size=-1):
		if self.parsedMode.reading is False:
			raise IOError("This file object is not readable")
		return super().read(size)

	def write(self, data):
		if self.parsedMode.writing is False:
			raise IOError("This file object is not writable")
		return super().write(data)

	def readable(self):
		return self.parsedMode.reading

	def writable(self):
		return self.parsedMode.writing

	@property
	def closed(self):
		return self._closed	

	def close(self):
		if self.parsedMode.writing:
			if self.itemId is None:
				# we have to create a new file
				parentDir = dirname(self.path)
				response = self.session.get(_PathUrl(parentDir, ""))
				response.raise_for_status()
				parentId = response.json()["id"]
				filename = basename(self.path)
				response = self.session.put(_ItemUrl(parentId, f":/{filename}:/content"), data=self.getvalue())
				response.raise_for_status()
			else:
				# upload a new version
				response = self.session.put(_ItemUrl(self.itemId, "/content"), data=self.getvalue())
				response.raise_for_status()
		self._closed = True

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
			"read_only": False,
			"supports_rename": False # since we don't have a syspath...
		}

	def __repr__(self):
		return f"<{self.__class__.__name__}>"

	# Translates OneDrive DriveItem dictionary to an fs Info object
	def _itemInfo(self, item): # pylint: disable=no-self-use
		# Looks like the dates returned directly in item.file_system_info (i.e. not file_system_info) are UTC naive-datetimes
		# We're supposed to return timestamps, which the framework can convert to UTC aware-datetimes
		rawInfo = {
			"basic": {
				"name": item["name"],
				"is_dir": "folder" in item,
			},
			"details": {
				"accessed": None, # not supported by OneDrive
				"created": datetime_to_epoch(_ParseDateTime(item["createdDateTime"])),
				"metadata_changed": None, # not supported by OneDrive
				"modified": datetime_to_epoch(_ParseDateTime(item["lastModifiedDateTime"])),
				"size": item["size"],
				"type": ResourceType.directory if "folder" in item else ResourceType.file,
			},
			"file_system_info": {
				"client_created": datetime_to_epoch(_ParseDateTime(item["fileSystemInfo"]["createdDateTime"])),
				"client_modified": datetime_to_epoch(_ParseDateTime(item["fileSystemInfo"]["lastModifiedDateTime"]))
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
					"taken_date_time": _ParseDateTime(item["photo"]["takenDateTime"]),
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
		response = self.session.get(_PathUrl(path, ""))
		if response.status_code == 404:
			raise ResourceNotFound(path=path)
		return self._itemInfo(response.json())

	def setinfo(self, path, info): # pylint: disable=too-many-branches
		response = self.session.get(_PathUrl(path, ""))
		if response.status_code == 404:
			raise ResourceNotFound(path=path)
		existingItem = response.json()
		updatedData = {}

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
						if "fileSystemInfo" not in updatedData:
							updatedData["fileSystemInfo"] = {}
						updatedData["fileSystemInfo"]["createdDateTime"] = epoch_to_datetime(value).replace(tzinfo=None).isoformat() + "Z"
					elif name == "metadata_changed":
						pass # not supported by OneDrive
					elif name == "modified":
						# incoming datetimes should be utc timestamps, OneDrive expects naive UTC datetimes
						if "fileSystemInfo" not in updatedData:
							updatedData["fileSystemInfo"] = {}
						updatedData["fileSystemInfo"]["lastModifiedDateTime"] = epoch_to_datetime(value).replace(tzinfo=None).isoformat() + "Z"
					elif name == "size":
						assert False, "Can't change item size"
					elif name == "type":
						assert False, "Can't change an item to and from directory"
					else:
						assert False, "Aren't we guaranteed that this is all there is in the details namespace?"
				else:
					# ignore namespaces that we don't recognize
					pass
		response = self.session.patch(_ItemUrl(existingItem["id"], ""), json=updatedData)
		response.raise_for_status()

	def listdir(self, path):
		return [x.name for x in self.scandir(path)]

	def makedir(self, path, permissions=None, recreate=False):
		parentDir = dirname(path)
		# parentDir here is expected to have a leading slash
		assert parentDir[0] == "/"
		response = self.session.get(_PathUrl(parentDir, ""))
		if response.status_code == 404:
			raise ResourceNotFound(parentDir)
		response.raise_for_status()

		if recreate is False:
			response = self.session.get(_PathUrl(path, ""))
			if response.status_code != 404:
				raise DirectoryExists(path)

		response = self.session.post(_PathUrl(parentDir, ":/children"),
			json={"name": basename(path), "folder": {}})
		# TODO - will need to deal with these errors locally but don't know what they are yet
		response.raise_for_status()
		# don't need to close this filesystem so we return the non-closing version
		return SubFS(self, path)

	def openbin(self, path, mode="r", buffering=-1, **options):
		if "t" in mode:
			raise ValueError("Text mode is not allowed in openbin")
		parsedMode = Mode(mode)
		exists = self.exists(path)
		if parsedMode.exclusive and exists:
			raise FileExists(path)
		elif parsedMode.reading and not parsedMode.create and not exists:
			raise ResourceNotFound(path)
		elif self.isdir(path):
			raise FileExpected(path)
		if parsedMode.writing:
			# make sure that the parent directory exists
			parentDir = dirname(path)
			response = self.session.get(_PathUrl(parentDir, ""))
			if response.status_code == 404:
				raise ResourceNotFound(parentDir)
			response.raise_for_status()
		itemId = None
		if exists:
			response = self.session.get(_PathUrl(path, ""))
			response.raise_for_status()
			itemId = response.json()["id"]
		return _UploadOnClose(session=self.session, path=path, itemId=itemId, mode=parsedMode)

	def remove(self, path):
		response = self.session.get(_PathUrl(path, ""))
		if response.status_code == 404:
			raise ResourceNotFound(path)
		response.raise_for_status()
		itemData = response.json()
		if "folder" in itemData:
			raise FileExpected(path=path)
		response = self.session.delete(_PathUrl(path, ""))
		response.raise_for_status()

	def removedir(self, path):
		# need to get the item id for this path
		response = self.session.get(_PathUrl(path, ""))
		if response.status_code == 404:
			raise ResourceNotFound(path)
		itemData = response.json()
		if "folder" not in itemData:
			raise DirectoryExpected(path)

		response = self.session.get(_PathUrl(path, ":/children"))
		response.raise_for_status()
		childrenData = response.json()
		if len(childrenData["value"]) > 0:
			raise DirectoryNotEmpty(path)

		itemId = itemData["id"] # let JSON parsing exceptions propagate for now
		response = self.session.delete(_ItemUrl(itemId, ""))
		assert response.status_code == 204, itemId # this is according to the spec

	# non-essential method - for speeding up walk
	def scandir(self, path, namespaces=None, page=None):
		response = self.session.get(_PathUrl(path, "")) # assumes path is the full path, starting with "/"
		if response.status_code == 404:
			raise ResourceNotFound(path=path)
		if "folder" not in response.json():
			raise DirectoryExpected(path=path)
		response = self.session.get(_PathUrl(path, ":/children")) # assumes path is the full path, starting with "/"
		if response.status_code == 404:
			raise ResourceNotFound(path=path)
		parsedResult = response.json()
		assert "@odata.context" in parsedResult
		if page is not None:
			return (self._itemInfo(x) for x in parsedResult["value"][page[0]:page[1]])
		return (self._itemInfo(x) for x in parsedResult["value"])

	def move(self, src_path, dst_path, overwrite=False):
		if not overwrite and self.exists(dst_path):
			raise DestinationExists(dst_path)
		driveItemResponse = self.session.get(_PathUrl(src_path, ""))
		if driveItemResponse.status_code == 404:
			raise ResourceNotFound(src_path)
		driveItemResponse.raise_for_status()
		driveItem = driveItemResponse.json()

		if "folder" in driveItem:
			raise FileExpected(src_path)

		itemUpdate = {}

		newFilename = basename(dst_path)
		if not self.isdir(dst_path) and newFilename != basename(src_path):
			itemUpdate["name"] = newFilename

		parentDir = dirname(dst_path)
		if parentDir != dirname(src_path):
			parentDirItem = self.session.get(_PathUrl(parentDir, ""))
			if parentDirItem.status_code == 404:
				raise ResourceNotFound(parentDir)
			parentDirItem.raise_for_status()
			itemUpdate["parentReference"] = {"id": parentDirItem.json()["id"]}

		itemId = driveItem["id"]
		response = self.session.patch(_ItemUrl(itemId, ""), json=itemUpdate)
		if response.status_code == 409 and overwrite is True:
			# delete the existing version and then try again
			response = self.session.delete(_PathUrl(dst_path, ""))
			response.raise_for_status()

			# check that it was deleted
			# response = self.session.get(_PathUrl(dst_path, ""))
			# assert response.status_code == 404, f"File {dst_path} should have been deleted"

			# try again
			print(f"Deleted existing file, updating again to {itemUpdate}")
			response = self.session.patch(_ItemUrl(itemId, ""), json=itemUpdate)
			response.raise_for_status()
			return
		response.raise_for_status()
