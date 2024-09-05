# fs.onedrivefs

Implementation of pyfilesystem2 file system using OneDrive

![image](https://github.com/rkhwaja/fs.onedrivefs/workflows/ci/badge.svg) [![codecov](https://codecov.io/gh/rkhwaja/fs.onedrivefs/branch/master/graph/badge.svg)](https://codecov.io/gh/rkhwaja/fs.onedrivefs) [![PyPI version](https://badge.fury.io/py/fs.onedrivefs.svg)](https://badge.fury.io/py/fs.onedrivefs)

# Usage

`fs.onedrivefs` can create a [`requests_oauthlib.OAuth2Session`](https://requests-oauthlib.readthedocs.io/en/latest/oauth2_workflow.html#) for you. This way the `OAuth2Session` is going to refresh the tokens for you.

``` python
onedriveFS = OneDriveFS(
  clientId=<your client id>,
  clientSecret=<your client secret>,
  token=<token JSON saved by oauth2lib>,
  SaveToken=<function which saves a new token string after refresh>)

# onedriveFS is now a standard pyfilesystem2 file system
```

You can handle the tokens outside of the library by passing a [`requests.Session`](https://requests.readthedocs.io/en/latest/user/advanced/#session-objects).
Here is an example of a custom session using [MSAL Python](https://learn.microsoft.com/en-us/entra/msal/python/)

``` python
class MSALSession(OAuth2Session):
  def __init__(self, client: msal.ClientApplication):
    super().__init__()
    self.client = client

  def request(self, *args, **kwargs):
    account = self.client.get_accounts()[0]
    self.token = self.client.acquire_token_silent_with_error(
      scopes=["Files.ReadWrite"], account=account
    )

    return super().request(*args, **kwargs)

client = msal.ConfidentialClientApplication(
  client_id=<your client id>,
  client_credential=<your client secret>,
  authority=f"https://login.microsoftonline.com/<your tenant>",
  token_cache=<your token cache>,
)

# Authentication flow to populate the token cache
# YOUR AUTHENTICATION FLOW

session = MSALSession(client=client)
onedriveFS = OneDriveFS(session=session)

# onedriveFS is now a standard pyfilesystem2 file system
```

Register your app [here](https://docs.microsoft.com/en-us/graph/auth-register-app-v2) to get a client ID and secret
