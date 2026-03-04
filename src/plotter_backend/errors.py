from __future__ import annotations


class BackendError(Exception):
    """Base error for backend pipeline/runtime failures."""


class ConversionError(BackendError):
    """Raised when source format conversion fails."""


class ToolDependencyError(ConversionError):
    """Raised when external conversion tooling is unavailable."""


class SerialTransportError(BackendError):
    """Raised on serial transport/protocol communication failures."""


class PipelineValidationError(BackendError):
    """Raised when input or runtime pipeline preconditions are invalid."""

