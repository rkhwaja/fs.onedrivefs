# coding: utf-8

from __future__ import unicode_literals
from __future__ import absolute_import

from os.path import join, realpath

import fs

# Add the local code directory to the `fs` module path
fs.__path__.insert(0, realpath(join(__file__, "..", "..", "fs")))
