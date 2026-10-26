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
    pass


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
