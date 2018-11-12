from time import time

from .base import Opener
from ..onedrivefs.onedrivefs_graph_api import OneDriveFSGraphAPI

def _SaveToken(token):
	pass

class OneDriveFSGraphAPIOpener(Opener):
	protocols = ["onedrive"]

	@staticmethod
	def open_fs(fs_url, parse_result, writeable, create, cwd):
		_, _, directory = parse_result.resource.partition('/')

		# this is missing various fields that hopefully aren't necessary
		token = {
			"token_type": "Bearer",
			"access_token": parse_result.params.get("access_token"),
			"refresh_token": parse_result.params.get("refresh_token")
		}		

		fs = OneDriveFSGraphAPI(
			clientId=parse_result.params["client_id"],
			clientSecret=parse_result.params.get("client_secret"),
			token=token,
			SaveToken=_SaveToken)

		if directory:
			return fs.opendir(directory)
		else:
			return fs
