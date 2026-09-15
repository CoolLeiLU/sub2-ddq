from __future__ import annotations


class MonitorRequestError(RuntimeError):
    """Raised when an external Sub2API request cannot be trusted."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
