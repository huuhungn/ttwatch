"""The app version. Bump it together with the CHANGELOG, before pushing a `v<version>` tag.

release.yml refuses to build a tag that does not match this value: a binary that reports an older
version than its own release would offer itself as an update forever.
"""
__version__ = "0.2.0"
