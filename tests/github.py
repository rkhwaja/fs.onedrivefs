from base64 import b64encode
from json import dumps
from os import environ

from nacl import encoding, public
from requests import put
from requests.auth import HTTPBasicAuth

def _EncryptForGithubSecret(publicKey, secretValue):
	publicKey = public.PublicKey(publicKey.encode('utf-8'), encoding.Base64Encoder())
	sealedBox = public.SealedBox(publicKey)
	encrypted = sealedBox.encrypt(secretValue.encode('utf-8'))
	return b64encode(encrypted).decode('utf-8')

def UploadSecret(token):
	auth = HTTPBasicAuth(environ['XGITHUB_USERNAME'], environ['XGITHUB_API_PERSONAL_TOKEN'])
	headers = {'Accept': 'application/vnd.github.v3+json'}

	owner = environ['XGITHUB_REPO_OWNER']
	baseUrl = f'https://api.github.com/repos/{owner}/fs.onedrivefs/actions/secrets'

	data = {
		'encrypted_value': _EncryptForGithubSecret(environ['XGITHUB_REPO_PUBLIC_KEY'], dumps(token)),
		'key_id': environ['XGITHUB_REPO_PUBLIC_KEY_ID']
		}

	response = put(f'{baseUrl}/GRAPH_API_TOKEN_READONLY', headers=headers, data=dumps(data), auth=auth)
	response.raise_for_status()
	print('Uploaded key to Github')
