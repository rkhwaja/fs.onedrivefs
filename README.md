# fs.onedrivefs

Implementation of pyfilesystem2 file system using OneDrive

![image](https://github.com/rkhwaja/fs.onedrivefs/workflows/ci/badge.svg) [![codecov](https://codecov.io/gh/rkhwaja/fs.onedrivefs/branch/master/graph/badge.svg)](https://codecov.io/gh/rkhwaja/fs.onedrivefs) [![PyPI version](https://badge.fury.io/py/fs.onedrivefs.svg)](https://badge.fury.io/py/fs.onedrivefs)

# Usage

``` python
onedriveFS = OneDriveFS(
  clientId=<your client id>,
  clientSecret=<your client secret>,
  token=<token JSON saved by oauth2lib>,
  SaveToken=<function which saves a new token string after refresh>)

# onedriveFS is now a standard pyfilesystem2 file system
```
