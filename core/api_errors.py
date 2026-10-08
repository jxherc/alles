from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class ApiError(HTTPException):
    """HTTP error with a stable machine-readable code and a human message."""

    def __init__(self, status_code: int, code: str, message: str, headers: dict | None = None):
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code


async def api_error_handler(_request: Request, error: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={"detail": error.detail, "code": error.code},
        headers=error.headers,
    )
