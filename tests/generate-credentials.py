#!/usr/bin/env python

from json import dump, load
from logging import basicConfig, DEBUG
from os import environ
from sys import stdout

from requests_oauthlib import OAuth2Session

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

def Authorize(clientId, clientSecret, redirectUri, storagePath):
	authorizationBaseUrl = "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize"
	tokenUrl = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
	session = OAuth2Session(client_id=clientId, redirect_uri=redirectUri, scope=["offline_access", "Files.ReadWrite"])
	authorizationUrl, state = session.authorization_url(authorizationBaseUrl)
	print(f"Go to the following URL and authorize the app: {authorizationUrl}")

	try:
		from pyperclip import copy
		copy(authorizationUrl)
		print("URL copied to clipboard")
	except ImportError:
		pass

	redirectResponse = input("Paste the full redirect URL here:")

	tokenStorage = TokenStorageFile(storagePath)

	environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "some value"
	token = session.fetch_token(tokenUrl, client_secret=clientSecret, authorization_response=redirectResponse)
	tokenStorage.Save(token)
	return token

if __name__ == "__main__":
	basicConfig(stream=stdout, level=DEBUG, format="{levelname[0]}|{module}|{lineno}|{message}", style="{")
	token = Authorize(environ["GRAPH_API_CLIENT_ID"], environ["GRAPH_API_CLIENT_SECRET"], environ["GRAPH_API_REDIRECT_URI"], environ["GRAPH_API_TOKEN_PATH"])
	print(token)