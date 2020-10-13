#!/usr/bin/env python

from base64 import b64encode
from json import dump, dumps, load
from logging import basicConfig, DEBUG
from os import environ
from sys import stdout

from nacl import encoding, public
from pyperclip import copy
from requests import put
from requests.auth import HTTPBasicAuth
from requests_oauthlib import OAuth2Session

class TokenStorageFile:
	def __init__(self, path):
		self.path = path

	def Save(self, token_):
		with open(self.path, 'w') as f:
			dump(token_, f)

	def Load(self):
		try:
			with open(self.path, 'r') as f:
				return load(f)
		except FileNotFoundError:
			return None

def EncryptForGithubSecret(publicKey: str, secretValue: str) -> str:
	"""Encrypt a Unicode string using the public key."""
	publicKey = public.PublicKey(publicKey.encode('utf-8'), encoding.Base64Encoder())
	sealedBox = public.SealedBox(publicKey)
	encrypted = sealedBox.encrypt(secretValue.encode('utf-8'))
	return b64encode(encrypted).decode('utf-8')

def Authorize(clientId, clientSecret, redirectUri, storagePath):
	authorizationBaseUrl = 'https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize'
	tokenUrl = 'https://login.microsoftonline.com/consumers/oauth2/v2.0/token'
	session = OAuth2Session(client_id=clientId, redirect_uri=redirectUri, scope=['offline_access', 'Files.ReadWrite'])
	authorizationUrl, _ = session.authorization_url(authorizationBaseUrl)
	print(f'Go to the following URL and authorize the app: {authorizationUrl}')

	copy(authorizationUrl)
	print('URL copied to clipboard')

	redirectResponse = input('Paste the full redirect URL here:')

	tokenStorage = TokenStorageFile(storagePath)

	environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = 'some value'
	token_ = session.fetch_token(tokenUrl, client_secret=clientSecret, authorization_response=redirectResponse)
	tokenStorage.Save(token_)
	if 'GITHUB_API_PERSONAL_TOKEN' in environ:
		auth = HTTPBasicAuth(environ['GITHUB_USERNAME'], environ['GITHUB_API_PERSONAL_TOKEN'])
		headers = {'Accept': 'application/vnd.github.v3+json'}

		owner = environ['GITHUB_REPO_OWNER']
		baseUrl = f'https://api.github.com/repos/{owner}/fs.onedrivefs/actions/secrets'

		data = {
			'encrypted_value': EncryptForGithubSecret(environ['GITHUB_REPO_PUBLIC_KEY'], dumps(token_)),
			'key_id': environ['GITHUB_REPO_PUBLIC_KEY_ID']
			}

		response = put(f'{baseUrl}/GRAPH_API_TOKEN_READONLY', headers=headers, data=dumps(data), auth=auth)
		response.raise_for_status()
		print('Uploaded key to Github')
	return token_

def EscapeForBash(token_):
	charactersToEscape = '{}\"[]: *!+/~^()'
	for character in charactersToEscape:
		token_ = token_.replace(character, '\\' + character)
	return token_

if __name__ == '__main__':
	basicConfig(stream=stdout, level=DEBUG, format='{levelname[0]}|{module}|{lineno}|{message}', style='{')
	token = Authorize(environ['GRAPH_API_CLIENT_ID'], environ['GRAPH_API_CLIENT_SECRET'], environ['GRAPH_API_REDIRECT_URI'], environ['GRAPH_API_TOKEN_PATH'])
	print(token)
