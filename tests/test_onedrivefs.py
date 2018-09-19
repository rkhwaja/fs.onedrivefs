#!/usr/bin/env python3

from datetime import datetime
from json import dump, load
from os import environ
from os.path import exists
from time import time

from onedrivesdk import AuthProvider, HttpProvider, OneDriveClient
from onedrivesdk.session import Session

from fs.time import datetime_to_epoch
from fs.onedrivefs import OneDriveFS

class JsonSession(Session):
	redirectUri = environ["ONEDRIVESDK_REDIRECT_URI"]
	clientSecret = environ["ONEDRIVESDK_CLIENT_SECRET"]
	clientId = environ["ONEDRIVESDK_CLIENT_ID"]

	def save_session(self, **save_session_kwargs):
		with open("session.json", "w") as f:
			dump({
				"token_type": self.token_type,
				"expires_at": self._expires_at,
				"scope": self.scope,
				"access_token": self.access_token,
				"client_id": self.client_id,
				"auth_server_url": self.auth_server_url,
				"redirect_uri": self.redirect_uri,
				"refresh_token": self.refresh_token,
				"client_secret": self.client_secret
			}, f)

	@staticmethod
	def load_session(**load_session_kwargs):
		with open("session.json", "r") as f:
			data = load(f)
		return JsonSession(
			token_type=data["token_type"],
			expires_in=data["expires_at"] - time(),
			scope_string=" ".join(data["scope"]),
			access_token=data["access_token"],
			client_id=data["client_id"],
			auth_server_url=data["auth_server_url"],
			redirect_uri=data["redirect_uri"],
			refresh_token=data["refresh_token"],
			client_secret=data["client_secret"]
			)

def Authorize(auth_provider, redirect_uri, client_secret):
	auth_url = auth_provider.get_auth_url(redirect_uri)

	print("Auth URL copied to clipboard: " + auth_url)
	from pyperclip import copy
	copy(auth_url)
	code = input("Code: ")

	auth_provider.authenticate(code, redirect_uri, client_secret)
	auth_provider.save_session()

def TestMisc():
	if not exists("session.json"):
		httpProvider = HttpProvider()
		authProvider = AuthProvider(http_provider=httpProvider, client_id=environ["ONEDRIVESDK_CLIENT_ID"], scopes=["wl.signin", "wl.offline_access", "onedrive.readwrite"], session_type=JsonSession)
		client = OneDriveClient("https://api.onedrive.com/v1.0/", authProvider, httpProvider)
		Authorize(client.auth_provider, environ["ONEDRIVESDK_REDIRECT_URI"], environ["ONEDRIVESDK_CLIENT_SECRET"])

	fs = OneDriveFS(environ["ONEDRIVESDK_CLIENT_ID"], JsonSession)

	with fs.openbin("/Documents/test2.txt", "w") as f:
		f.write("This is a test")

	path = "/Documents/test.txt"
	originalInfo = fs.getinfo(path, ['details'])
	print(f"Original created: {originalInfo.created}")
	print(f"Original modified: {originalInfo.modified}")
	# assert False
	newCreated = datetime(2000, 1, 1, 0, 0, 0)
	newModified = datetime(2010, 1, 1, 0, 0, 0)
	assert originalInfo.created != newCreated, f"Original: {originalInfo.created}"
	assert originalInfo.modified != newModified, f"Modified: {originalInfo.modified}"
	fs.setinfo(path, {"details": {"created": datetime_to_epoch(newCreated), "modified": datetime_to_epoch(newModified)}})
	newInfo = fs.getinfo(path, ['details'])
	assert newInfo.created.replace(tzinfo=None) == newCreated, f"New: {newInfo.created}"
	assert newInfo.modified.replace(tzinfo=None) == newModified, f"New: {newInfo.modified}"
	fs.setinfo(path, {"details": {"created": datetime_to_epoch(originalInfo.created), "modified": datetime_to_epoch(originalInfo.modified)}})

	# d = "2012-11-27T03:43:00"
	# dt = datetime.strptime(d, "%Y-%m-%dT%H:%M:%S")
	# print(f"dt: {dt}")
	# path = "/Pictures/archive/archive00/archive000/2012-11-26-17-04-41-pb262844.dng"
	# fs.setinfo(path=path, info={"details": {"modified": dt}})
	# info = fs.getinfo(path=path)
	# assert info.get("details", "modified") == dt

	# print(fs.listdir("/Documents"))
	# ti = fs.getinfo("/Pictures/archive/archive00/archive009/2008-10-19-16-57-17-P1010112.JPG", ['details'])
	# print(ti)
	# print(ti._to_datetime)

	# fs2 = fs.opendir("/Pictures/archive")
	# ti = fs2.getinfo("/archive00/archive000/2012-11-26-17-04-41-pb262844.dng", ['details'])
	# print(ti)
	# print(ti._to_datetime)

	# print(fs.listdir("/Documents/big-directory"))

	# print(fs.getinfo("/Pictures/archive/archive00"))
	# print(fs.listdir("/Pictures/archive/archive00"))
	# print(fs.getinfo("/Pictures"))
	# print(fs.getinfo("/Videos/foo.txt").created)
	# fs.setinfo("/Videos/foo.txt", )
	# print(fs.listdir("/Documents"))
	# print(fs.listdir("/Videos"))

	# print(fs.makedir("/Documents/test"))
	# assert "test" in fs.listdir("/Documents")
	# fs.removedir("/Documents/test")
	# assert "test" not in fs.listdir("/Documents")

	# try:
	# 	fs.makedir("/Documentsx/test")
	# except NameError:
	# 	pass
	# except:
	# 	print("Wrong exception thrown")

	# f = fs.openbin("/Videos/foo2.txt", "r")
	# print(f)
	# print(f.read())

	# videosDir = fs.opendir("/Videos")
	# videosDir.tree()

	# doesn't work without fully implementing openbin
	# fs.move("/Documents/test.txt", "/Documents/test2.txt")

	assert fs.hassyspath("/") is False

if __name__ == "__main__":
	TestMisc()
