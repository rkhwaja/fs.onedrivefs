# coding: utf-8
from __future__ import absolute_import
from __future__ import unicode_literals

from datetime import datetime, timedelta, timezone
from hashlib import sha1
from json import dump, load, loads
from logging import info, warning
from os import environ
from time import sleep
from unittest import TestCase
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import uuid4

from fs.onedrivefs import OneDriveFS, OneDriveFSOpener
from fs.opener import open_fs, registry
from fs.subfs import SubFS
from fs.test import FSTestCases
from pyngrok.ngrok import connect # pylint: disable=wrong-import-order
from pytest import fixture, mark # pylint: disable=wrong-import-order
from pytest_localserver.http import WSGIServer # pylint: disable=wrong-import-order

_SAFE_TEST_DIR = "Documents/test-onedrivefs"

class InMemoryTokenSaver: # pylint: disable=too-few-public-methods
	def __init__(self, path):
		self.path = path

	def __call__(self, token):
		with open(self.path, "w") as f:
			dump(token, f)

class TokenStorageReadOnly:
	def __init__(self, token):
		self.token = token

	def Save(self, token):
		self.token = token

	def Load(self):
		return loads(self.token)

class TokenStorageFile:
	def __init__(self, path):
		self.path = path

	def Save(self, token):
		with open(self.path, "w") as f:
			dump(token, f)

	def Load(self):
		try:
			with open(self.path, "r") as f:
				return load(f)
		except FileNotFoundError:
			return None

class simple_app: # pylint: disable=too-few-public-methods
	def __init__(self):
		self.notified = False

	def __call__(self, environ_, start_response):
		"""Simplest possible WSGI application"""
		status = "200 OK"
		response_headers = [("Content-type", "text/plain")]
		start_response(status, response_headers)
		parsedQS = parse_qs(environ_["REQUEST_URI"][2:])
		info(f"Received: {parsedQS}")
		info(f"env: {environ_}")
		if "validationToken" in parsedQS:
			info("Validating subscription")
			return [parsedQS["validationToken"][0].encode()]
		inputStream = environ_["wsgi.input"]
		info(f"Input: {inputStream}")
		info("NOTIFIED")
		self.notified = True
		return ""

@fixture(scope="class")
def testserver(request):
	server = WSGIServer(application=simple_app())
	request.cls.server = server
	server.start()
	request.addfinalizer(server.stop)
	return server

def CredentialsStorage():
	if "GRAPH_API_TOKEN_READONLY" in environ:
		return TokenStorageReadOnly(environ["GRAPH_API_TOKEN_READONLY"])
	return TokenStorageFile(environ["GRAPH_API_TOKEN_PATH"])

def FullFS():
	storage = CredentialsStorage()
	return OneDriveFS(environ["GRAPH_API_CLIENT_ID"], environ["GRAPH_API_CLIENT_SECRET"], storage.Load(), storage.Save)

def test_list_root():
	fs = FullFS()
	assert fs.listdir("/") == fs.listdir("")

def test_opener_format():
	registry.install(OneDriveFSOpener())
	client_id = environ["GRAPH_API_CLIENT_ID"]
	client_secret = environ["GRAPH_API_CLIENT_SECRET"]
	credentials = CredentialsStorage().Load()
	access_token = credentials["access_token"]
	refresh_token = credentials["refresh_token"]

	encodedParameters = urlencode({"access_token": access_token, "refresh_token": refresh_token, "client_id": client_id, "client_secret": client_secret})

	# Without the initial "/" character, it should still be assumed to relative to the root
	fs = open_fs(f"onedrive://{_SAFE_TEST_DIR}?" + encodedParameters)
	assert isinstance(fs, SubFS), str(fs)
	assert fs._sub_dir == f"/{_SAFE_TEST_DIR}" # pylint: disable=protected-access

	# It should still accept the initial "/" character
	fs = open_fs(f"onedrive:///{_SAFE_TEST_DIR}?" + encodedParameters)
	assert isinstance(fs, SubFS), str(fs)
	assert fs._sub_dir == f"/{_SAFE_TEST_DIR}" # pylint: disable=protected-access

class TestOneDriveFS(FSTestCases, TestCase):
	def make_fs(self):
		self.fullFS = FullFS()
		self.testSubdir = f"/{_SAFE_TEST_DIR}/{uuid4()}"
		return self.fullFS.makedirs(self.testSubdir)

	def destroy_fs(self, _):
		self.fullFS.removetree(self.testSubdir)

	@mark.usefixtures("testserver")
	def test_subscriptions(self):
		port = urlparse(self.server.url).port # pylint: disable=no-member
		info(f"Port: {port}")
		info(self.server.url) # pylint: disable=no-member
		with open("ngrok.yml", "w") as f:
			f.write(f"authtoken: {environ['NGROK_AUTH_TOKEN']}")
		publicUrl = connect(proto="http", port=port, config_path="ngrok.yml").replace("http", "https")
		info(f"publicUrl: {publicUrl}")
		expirationDateTime = datetime.now(timezone.utc) + timedelta(minutes=5)
		id_ = self.fs.create_subscription(publicUrl, expirationDateTime, "client_state")
		info(f"subscription id: {id_}")
		self.fs.touch("touched-file.txt")
		info("Touched the file, waiting...")
		# subscription = self.fs.update_subscription(subscription["id"], expirationDateTime + timedelta(hours=12))
		# need to wait for some time for the notification to come through, but also process incoming http requests
		for _ in range(10):
			if self.server.app.notified is True: # pylint: disable=no-member
				break
			sleep(1)
		# sleep(2)
		info("Sleep done, deleting subscription")
		self.fs.delete_subscription(id_)
		info("subscription deleted")
		assert self.server.app.notified is True, f"Not notified: {self.server.app.notified}" # pylint: disable=no-member

	def test_overwrite_file(self):
		with self.fs.open("small_file_to_overwrite.bin", "wb") as f:
			f.write(b"x" * 10)

		with self.fs.open("small_file_to_overwrite.bin", "wb") as f:
			f.write(b"y" * 10)

		with self.fs.open("small_file_to_overwrite.txt", "w") as f:
			f.write("x" * 10)

		with self.fs.open("small_file_to_overwrite.txt", "w") as f:
			f.write("y" * 10)

		with self.fs.open("large_file_to_overwrite.bin", "wb") as f:
			f.write(b"x" * 4000000)

		with self.fs.open("large_file_to_overwrite.bin", "wb") as f:
			f.write(b"y" * 4000000)

		with self.fs.open("large_file_to_overwrite.txt", "w") as f:
			f.write("x" * 4000000)

		with self.fs.open("large_file_to_overwrite.txt", "w") as f:
			f.write("y" * 4000000)

	def test_photo_metadata(self):
		with self.fs.open("canon-ixus.jpg", "wb") as target:
			with open("tests/canon-ixus.jpg", "rb") as source:
				target.write(source.read())

		# sometimes it take a few seconds for the server to process EXIF data
		# until it's processed, the "photo" section should be missing
		for _ in range(3):
			info_ = self.fs.getinfo("canon-ixus.jpg")

			self.assertTrue(info_.get("photo", "camera_make") in [None, "Canon"])
			self.assertTrue(info_.get("photo", "camera_model") in [None, "Canon DIGITAL IXUS"])
			self.assertTrue(info_.get("photo", "exposure_denominator") in [None, 350])
			self.assertTrue(info_.get("photo", "exposure_numerator") in [None, 1])
			self.assertTrue(info_.get("photo", "focal_length") in [None, 10.8125])
			self.assertTrue(info_.get("photo", "f_number") in [None, 4.0])
			self.assertTrue(info_.get("photo", "taken_date_time") in [None, datetime(2001, 6, 9, 15, 17, 32)])
			self.assertTrue(info_.get("photo", "iso") in [None])
			self.assertTrue(info_.get("image", "width") in [None, 640])
			self.assertTrue(info_.get("image", "height") in [None, 480])
			if info_.get("photo", "camera_make") is not None:
				break
			sleep(5)
		else:
			self.fail("EXIF metadata not processed in 10s")

	def test_photo_metadata2(self):
		with self.fs.open("DSCN0010.jpg", "wb") as target:
			with open("tests/DSCN0010.jpg", "rb") as source:
				target.write(source.read())

		# sometimes it take a few seconds for the server to process EXIF data
		# until it's processed, the "photo" section should be missing
		iterations = 10
		sleepTime = 5
		for iteration in range(iterations):
			info_ = self.fs.getinfo("DSCN0010.jpg")

			self.assertTrue(info_.get("photo", "camera_make") in [None, "NIKON"])
			self.assertTrue(info_.get("photo", "camera_model") in [None, "COOLPIX P6000"])
			self.assertTrue(info_.get("photo", "exposure_denominator") in [None, 300.0])
			self.assertTrue(info_.get("photo", "exposure_numerator") in [None, 4.0])
			self.assertTrue(info_.get("photo", "focal_length") in [None, 24.0])
			self.assertTrue(info_.get("photo", "f_number") in [None, 5.9])
			self.assertTrue(info_.get("photo", "taken_date_time") in [None, datetime(2008, 10, 22, 16, 28, 39)])
			self.assertTrue(info_.get("photo", "iso") in [None, 64])
			self.assertTrue(info_.get("image", "width") in [None, 640])
			self.assertTrue(info_.get("image", "height") in [None, 480])
			self.assertTrue(info_.get("location", "latitude") in [None, 43.46744833333334])
			self.assertTrue(info_.get("location", "longitude") in [None, 11.885126666663888])
			if info_.get("photo", "camera_make") is not None:
				break
			warning(f"EXIF metadata not processed in {iteration * sleepTime}s")
			sleep(sleepTime)
		else:
			self.fail(f"EXIF metadata not processed in {iterations * sleepTime}s")

	def test_hashes(self):
		with self.fs.open("DSCN0010.jpg", "wb") as target:
			with open("tests/DSCN0010.jpg", "rb") as source:
				data = source.read()
				target.write(data)

		hash_ = sha1()
		hash_.update(data)

		self.assertEqual(hash_.hexdigest().upper(), self.fs.getinfo("DSCN0010.jpg").get("hashes", "SHA1"))
