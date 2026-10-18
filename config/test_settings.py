"""
Dedicated test settings for Newtonite Task Tracker.
Uses standard StaticFilesStorage for automated test execution so that template
rendering does not require a pre-compiled staticfiles.json manifest, while preserving
all production settings, WhiteNoise middleware, and database configuration.
"""
from .settings import *

# Explicitly use standard StaticFilesStorage during automated test execution
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# Also set legacy STATICFILES_STORAGE for any third-party tools or Django fallback
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

# Avoid WhiteNoise missing staticfiles directory warning when testing in clean environments
WHITENOISE_AUTOREFRESH = True

# Fast password hasher for test speed
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]
