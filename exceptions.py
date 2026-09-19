class EcoCashError(Exception):
    pass


class EcoCashAPIError(EcoCashError):
    def __init__(self, message: str, status_code: int | None = None, response: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class EcoCashAuthError(EcoCashAPIError):
    pass


class EcoCashValidationError(EcoCashError):
    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.field = field


class EcoCashTimeoutError(EcoCashError):
    pass


class EcoCashNetworkError(EcoCashError):
    pass
