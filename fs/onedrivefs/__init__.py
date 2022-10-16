from logging import getLogger, NullHandler

from .onedrivefs import OneDriveFS
from .opener import OneDriveFSOpener

getLogger(__name__).addHandler(NullHandler())
