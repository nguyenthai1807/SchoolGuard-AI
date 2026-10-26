"""Auth/account probe for future cloud staging; no media or billing endpoints.

Do not deploy as the full LH25 product. The local app deliberately remains
blocked on Cloud Run until durable jobs, media, payments and MFA are ready.
"""

from fastapi import FastAPI, HTTPException, Request, Response

from .cloud_access import CloudAccessDenied, resolve_access
from .cloud_auth import CloudAuthRejected, CloudAuthUnavailable


def create_cloud_api(*, verifier, access_reader, required_terms_version: str) -> FastAPI:
    if (not getattr(verifier, "project_id", None)
            or verifier.project_id != getattr(access_reader, "project_id", None)):
        raise ValueError("Token verifier and rights store must use the same project")
    if not isinstance(required_terms_version, str) or not required_terms_version.endswith("-cloud"):
        raise ValueError("Cloud-specific terms are required")

    app = FastAPI(title="LH25 cloud account probe", docs_url=None, redoc_url=None,
                  openapi_url=None)

    @app.middleware("http")
    async def response_headers(request: Request, call_next):
        result = await call_next(request)
        result.headers["Cache-Control"] = "no-store"
        result.headers["X-Content-Type-Options"] = "nosniff"
        return result

    @app.get("/healthz")
    def healthz():
        return {"status": "up", "scope": "auth-probe-only"}

    @app.get("/api/cloud/me")
    def current_access(request: Request):
        try:
            principal = verifier.authenticate(request.headers.get("authorization"))
        except CloudAuthRejected as exc:
            raise HTTPException(401, "Tài khoản chưa được xác minh.") from exc
        except CloudAuthUnavailable as exc:
            raise HTTPException(503, "Tạm thời không xác minh được tài khoản.") from exc
        try:
            access = resolve_access(principal, access_reader,
                                    required_terms_version=required_terms_version)
        except CloudAccessDenied as exc:
            raise HTTPException(403, "Tài khoản chưa đủ điều kiện dùng bản cloud.") from exc
        except Exception as exc:
            # Firestore timeout/outage: never grant Free, Pro or Admin by default.
            raise HTTPException(503, "Tạm thời không kiểm tra được quyền truy cập.") from exc
        return {"uid": access.uid, "plan": access.plan,
                "can_use_pro": access.can_use_pro, "is_admin": access.is_admin}

    return app
