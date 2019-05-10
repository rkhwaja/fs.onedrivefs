fs.onedrivefs
=============

Implementation of pyfilesystem2 file system using OneDrive

.. image:: https://travis-ci.org/rkhwaja/fs.onedrivefs.svg?branch=master
   :target: https://travis-ci.org/rkhwaja/fs.onedrivefs

Usage
=====

.. code-block:: python

  onedriveFS = OneDriveFS(
    clientId=<your client id>,
    clientSecret=<your client secret>,
    token=<token JSON saved by oauth2lib>,
    SaveToken=<function which saves a new token string after refresh>)

  # onedriveFS is now a standard pyfilesystem2 file system
