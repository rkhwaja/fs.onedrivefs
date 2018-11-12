fs.onedrivefs
=============

Implementation of pyfilesystem2 file system using OneDrive

Usage
=====

.. code-block:: python

  onedriveFS = OneDriveFSGraphAPI(
    clientId=<your client id>,
    clientSecret=<your client secret>,
    token=<token JSON saved by oauth2lib>,
    SaveToken=<function which saves a new token string after refresh>)

  # onedriveFS is now a standard pyfilesystem2 file system
