class AppError(Exception):
    pass


class DocumentNotFoundError(AppError):
    pass


class UnsupportedFormatError(AppError):
    pass


class IngestionError(AppError):
    pass


class RetrievalError(AppError):
    pass


class LLMError(AppError):
    pass


class LLMRateLimitError(LLMError):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ConfigurationError(AppError):
    pass


class UploadTooLargeError(AppError):
    pass


class AccessDeniedError(AppError):
    pass


class ServiceUnavailableError(AppError):
    pass


class InvalidRequestError(AppError):
    pass


class MigrationError(AppError):
    pass
