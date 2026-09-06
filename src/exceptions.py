from __future__ import annotations


class ConfigError(ValueError):
    """Raised when a configuration error occurs."""


class SourceError(ValueError):
    """Raised when a source error occurs."""


class StorageError(ValueError):
    """Raised when a storage error occurs."""


class RedeemerError(ValueError):
    """Raised when a redemption error occurs."""


class SourceValidationError(ValueError):
    """Raised when source validation fails."""
