__all__ = ['OneDriveFSOpener']

from fs.opener import Opener

from .onedrivefs import OneDriveFS

def _SaveToken(_):
	pass

class OneDriveFSOpener(Opener): # pylint: disable=too-few-public-methods
	protocols = ['onedrive']

	@staticmethod
	def open_fs(fs_url, parse_result, writeable, create, cwd): # pylint: disable=unused-argument
		directory = parse_result.resource

		# this is missing various fields that hopefully aren't necessary
		token = {
			'token_type': 'Bearer',
			'access_token': parse_result.params.get('access_token'),
			'refresh_token': parse_result.params.get('refresh_token')
		}

		fs = OneDriveFS(
			clientId=parse_result.params['client_id'],
			clientSecret=parse_result.params.get('client_secret'),
			token=token,
			SaveToken=_SaveToken,
			driveId=parse_result.params.get('drive_id'),
			userId=parse_result.params.get('user_id'),
			groupId=parse_result.params.get('group_id'),
			siteId=parse_result.params.get('site_id'),
		)

		if directory:
			return fs.opendir(directory)
		return fs
