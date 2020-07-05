# fs.onedrivefs

Implementation of pyfilesystem2 file system using OneDrive

[![image](https://travis-ci.org/rkhwaja/fs.onedrivefs.svg?branch=master)](https://travis-ci.org/rkhwaja/fs.onedrivefs)

[![image](https://coveralls.io/repos/github/rkhwaja/fs.onedrivefs/badge.svg?branch=master)](https://coveralls.io/github/rkhwaja/fs.onedrivefs?branch=master)

# Usage

``` python
onedriveFS = OneDriveFS(
  clientId=<your client id>,
  clientSecret=<your client secret>,
  token=<token JSON saved by oauth2lib>,
  SaveToken=<function which saves a new token string after refresh>)

# onedriveFS is now a standard pyfilesystem2 file system
```
