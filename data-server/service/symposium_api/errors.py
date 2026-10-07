"""The API's one error body, `Error` in the contract: `{detail, code, findings?}`."""

from __future__ import annotations

CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    413: "too_large",
    422: "unprocessable",
    429: "too_many_streams",
    501: "not_operational",
}


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        detail: str,
        code: str | None = None,
        findings: list | None = None,
        headers: dict | None = None,
    ):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.code = code or CODES.get(status, "bad_request")
        self.findings = findings
        self.headers = headers

    def body(self) -> dict:
        out = {"detail": self.detail, "code": self.code}
        if self.findings is not None:
            out["findings"] = self.findings
        return out


def body_for(status: int, detail) -> dict:
    """The Error body for a refusal raised outside the API's own code (FastAPI, `/v1` helpers)."""
    if not isinstance(detail, str):
        detail = "; ".join(
            f"{'.'.join(str(p) for p in e.get('loc', ()))}: {e.get('msg')}"
            if isinstance(e, dict)
            else str(e)
            for e in (detail if isinstance(detail, list) else [detail])
        )
    return {"detail": detail, "code": CODES.get(status, "bad_request")}
