#!/usr/bin/env python

from base64 import b64encode
from json import dump, dumps, load
from logging import basicConfig, DEBUG, info
from os import environ
from sys import stdout

from msal import ConfidentialClientApplication
from pyperclip import copy
from requests import put
from requests.auth import HTTPBasicAuth
from requests_oauthlib import OAuth2Session

from github import UploadSecret

SCOPE = ['offline_access', 'Files.ReadWrite']

class TokenStorageFile:
	def __init__(self, path):
		self.path = path

	def Save(self, token_):
		with open(self.path, 'w', encoding='utf-8') as f:
			dump(token_, f)

	def Load(self):
		try:
			with open(self.path, encoding='utf-8') as f:
				return load(f)
		except FileNotFoundError:
			return None

def Authorize(clientId, clientSecret, redirectUri, storagePath):
	app = ConfidentialClientApplication(clientId,
		authority='https://login.microsoftonline.com/common',
		client_credential=clientSecret)
	
	scopeNew = ['8147afd6-b133-44cc-8098-216d561c11d0/.default']

	print(f'accounts: {app.get_accounts()}')
	
	result = None
	result = app.acquire_token_silent(scopeNew, account='a5e1e28f-afae-4b9a-b847-82ca6b6f2eb2')
	from pprint import pprint
	pprint("RESULT:")
	pprint(result)
	if not result:
		info("No suitable token exists in cache. Let's get a new one from AAD.")
		result = app.acquire_token_for_client(scopes=scopeNew)
	assert 'access_token' in result, result

def AuthorizeOld(clientId, clientSecret, redirectUri, storagePath):
	authorizationBaseUrl = 'https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize'
	tokenUrl = 'https://login.microsoftonline.com/consumers/oauth2/v2.0/token'
	session = OAuth2Session(client_id=clientId, redirect_uri=redirectUri, scope=SCOPE)
	authorizationUrl, _ = session.authorization_url(authorizationBaseUrl)
	print(f'Go to the following URL and authorize the app: {authorizationUrl}')

	copy(authorizationUrl)
	print('URL copied to clipboard')

	redirectResponse = input('Paste the full redirect URL here:')

	tokenStorage = TokenStorageFile(storagePath)

	environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = 'some value' # noqa: S105
	token_ = session.fetch_token(tokenUrl, client_secret=clientSecret, authorization_response=redirectResponse, include_client_id=True)
	tokenStorage.Save(token_)
	if 'XGITHUB_API_PERSONAL_TOKEN' in environ:
		UploadSecret(token_)
	return token_

if __name__ == '__main__':
	basicConfig(stream=stdout, level=DEBUG, format='{levelname[0]}|{module}|{lineno}|{message}', style='{')
	token = Authorize(
		environ['GRAPH_API_CLIENT_ID'],
		environ['GRAPH_API_CLIENT_SECRET'],
		environ['GRAPH_API_REDIRECT_URI'],
		environ['GRAPH_API_TOKEN_PATH']
	)
	print(token)
