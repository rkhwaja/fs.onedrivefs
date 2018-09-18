#!/usr/bin/env python

from json import dump, load
from os import environ

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
	authorizationBaseUrl = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
	tokenUrl = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
	session = OAuth2Session(client_id=clientId, redirect_uri=redirectUri, scope="Files.Read")
	authorizationUrl, _ = session.authorization_url(authorizationBaseUrl)
	# nope - it has to be a post
	print(f"Go to the following URL and authorize the app: {authorizationUrl}")

	try:
		from pyperclip import copy
		copy(authorizationUrl)
		print("URL copied to clipboard")
	except ImportError:
		pass

	redirectResponse = input("Paste the full redirect URL here:")

	tokenStorage = TokenStorageFile(storagePath)

	token = session.fetch_token(tokenUrl, client_secret=clientSecret, authorization_response=redirectResponse, token_updater=tokenStorage.Save)
	tokenStorage.Save(token)
	return token

if __name__ == "__main__":
	token = Authorize(environ["GRAPH_API_CLIENT_ID"], environ["GRAPH_API_CLIENT_SECRET"], environ["GRAPH_API_REDIRECT_URI"], environ["GRAPH_API_TOKEN_PATH"])
	print(token)
