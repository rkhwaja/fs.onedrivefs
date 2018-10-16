from time import time

from .base import Opener
from ..onedrivefs import OneDriveFS
from onedrivesdk.session import Session

class MemorySession(Session):
	access_token = None
	client_id = None
	expires_at = None
	scope_string = None # space-separated scopes
	auth_server_url = None
	redirect_uri = None
	refresh_token = None
	client_secret = None

	def save_session(self, **save_session_kwargs):
		pass

	@staticmethod
	def load_session(**load_session_kwargs):
		return MemorySession(
			token_type="bearer",
			expires_in=MemorySession.expires_at - time(),
			scope_string=MemorySession.scope_string,
			access_token=MemorySession.access_token,
			client_id=MemorySession.client_id,
			auth_server_url=MemorySession.auth_server_url,
			redirect_uri=MemorySession.redirect_uri,
			refresh_token=MemorySession.refresh_token,
			client_secret=MemorySession.client_secret
			)

class OneDriveOpener(Opener):
	protocols = ["onedriveold"]

	@staticmethod
	def open_fs(fs_url, parse_result, writeable, create, cwd):
		_, _, directory = parse_result.resource.partition('/')
		sessionType = MemorySession
		sessionType.client_id = parse_result.params["client_id"]
		sessionType.access_token = parse_result.params["access_token"]
		sessionType.expires_at = float(parse_result.params.get("expires_at"))
		sessionType.scope_string = parse_result.params.get("scope")
		sessionType.auth_server_url = parse_result.params.get("auth_server_url")
		sessionType.redirect_uri = parse_result.params.get("redirect_uri")
		sessionType.refresh_token = parse_result.params.get("refresh_token")
		sessionType.client_secret = parse_result.params.get("client_secret")

		fs = OneDriveFS(clientId=sessionType.client_id, sessionType=sessionType)

		if directory:
			return fs.opendir(directory)
		else:
			return fs
