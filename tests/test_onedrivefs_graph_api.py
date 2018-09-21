# coding: utf-8
from __future__ import absolute_import
from __future__ import unicode_literals

from json import dump, load
from os import environ
from unittest import TestCase
from uuid import uuid4

from fs.test import FSTestCases
from fs.onedrivefs.onedrivefs_graph_api import OneDriveFSGraphAPI

class InMemoryTokenSaver: # pylint: disable=too-few-public-methods
	def __init__(self, path):
		self.path = path

	def __call__(self, token):
		with open(self.path, "w") as f:
			dump(token, f)

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

class TestOneDriveFS(FSTestCases, TestCase):
	def make_fs(self):
		storage = TokenStorageFile(environ["GRAPH_API_TOKEN_PATH"])
		self.fullFS = OneDriveFSGraphAPI(environ["GRAPH_API_CLIENT_ID"], environ["GRAPH_API_CLIENT_SECRET"], storage.Load(), storage.Save) # pylint: disable=attribute-defined-outside-init
		self.testSubdir = "/Documents/test-onedrivefs/" + str(uuid4()) # pylint: disable=attribute-defined-outside-init
		return self.fullFS.makedirs(self.testSubdir)

	def destroy_fs(self, _):
		self.fullFS.removetree(self.testSubdir)
