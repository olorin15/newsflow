"""Shared exceptions."""


class NewsflowError(Exception):
    """Base error with a user-facing message."""


class ConfigError(NewsflowError):
    """Raised when configuration is missing or invalid."""
