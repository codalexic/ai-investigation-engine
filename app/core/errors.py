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
