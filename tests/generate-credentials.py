#!/usr/bin/env python

from json import dump, load
from logging import basicConfig, DEBUG
from os import environ
from sys import stdout

from pyperclip import copy
from requests_oauthlib import OAuth2Session

from github import UploadSecret

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
	authorizationBaseUrl = 'https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize'
	tokenUrl = 'https://login.microsoftonline.com/consumers/oauth2/v2.0/token'
	session = OAuth2Session(client_id=clientId, redirect_uri=redirectUri, scope=['offline_access', 'Files.ReadWrite'])
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

def EscapeForBash(token_):
	charactersToEscape = '{}"[]: *!+/~^()'
	for character in charactersToEscape:
		token_ = token_.replace(character, '\\' + character)
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
