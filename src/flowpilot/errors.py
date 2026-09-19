class DomainError(Exception):
    def __init__(self, status: int, code: str, detail: str):
        self.status = status
        self.code = code
        self.detail = detail
        super().__init__(detail)


class ExecutionError(Exception):
    def __init__(self, code: str, retryable: bool = False, retry_after: float | None = None):
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after
        super().__init__(code)
