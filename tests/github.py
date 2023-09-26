from base64 import b64encode
from json import dumps
from os import environ

from nacl import encoding, public
from requests import get, put
from requests.auth import HTTPBasicAuth

def _EncryptForGithubSecret(publicKey, secretValue):
	publicKey = public.PublicKey(publicKey.encode('utf-8'), encoding.Base64Encoder())
	sealedBox = public.SealedBox(publicKey)
	encrypted = sealedBox.encrypt(secretValue.encode('utf-8'))
	return b64encode(encrypted).decode('utf-8')

def UploadSecret(token):
	# needs a PAT with permissions to public repositories
	auth = HTTPBasicAuth(environ['XGITHUB_USERNAME'], environ['XGITHUB_API_PERSONAL_TOKEN'])
	headers = {'Accept': 'application/vnd.github.v3+json'}

	owner = environ['XGITHUB_REPO_OWNER']
	baseUrl = f'https://api.github.com/repos/{owner}/fs.onedrivefs/actions/secrets'
	publicKey = get(f'https://api.github.com/repos/{owner}/fs.onedrivefs/actions/secrets/public-key', headers=headers, auth=auth, timeout=30).json()

	data = {
		'encrypted_value': _EncryptForGithubSecret(publicKey['key'], dumps(token)),
		'key_id': publicKey['key_id']
		}

	response = put(f'{baseUrl}/GRAPH_API_TOKEN_READONLY', headers=headers, data=dumps(data), auth=auth, timeout=30)
	response.raise_for_status()
	print('Uploaded key to Github')
