"""Authenticated Guardian REST API v1 and static management UI routes."""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from starlette.routing import Route

from ..auth import ApiKeyAuthenticator, Principal, bind_principal
from ..config import Scope
from ..errors import ServiceError
from ..session import COOKIE_NAME, Session, SessionCodec
from .service import GuardianService

_STATIC_ROOT = Path(__file__).with_name("static")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _json_default(value: object) -> str:
    """Encode values that the standard json encoder rejects."""

    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


class GuardianJSONResponse(JSONResponse):
    """JSON response that can serialize the repository row shapes.

    Repository row mappers hand ``datetime`` values straight from asyncpg so
    the same structures feed both the API and the console.  Stock
    ``JSONResponse`` uses ``json.dumps`` without a ``default`` hook, so every
    route returning a timestamped record raises ``TypeError`` as soon as the
    table it reads has a row.
    """

    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
            default=_json_default,
        ).encode("utf-8")


_MEDIA_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".ico": "image/x-icon",
    ".map": "application/json",
}


class GuardianAPI:
    def __init__(
        self,
        service: GuardianService,
        authenticator: ApiKeyAuthenticator,
        audit: Callable[[str, str, str | None, str], Awaitable[None]],
        sessions: SessionCodec | None = None,
    ) -> None:
        self.service = service
        self._authenticator = authenticator
        self._audit = audit
        self._sessions = sessions
        self._login_attempts: dict[str, list[float]] = {}
        self._logger = logging.getLogger("sub2api_mcp.guardian.api")

    def routes(self) -> list[Route]:
        return [
            Route("/guardian", self.redirect_ui, methods=["GET"]),
            Route("/guardian/", self.ui, methods=["GET"]),
            Route("/guardian/assets/{path:path}", self.asset, methods=["GET"]),
            Route("/api/guardian/v1/session", self.session_state, methods=["GET"]),
            Route("/api/guardian/v1/login", self.login, methods=["POST"]),
            Route("/api/guardian/v1/logout", self.logout, methods=["POST"]),
            Route("/api/guardian/v1/overview", self.overview, methods=["GET"]),
            Route("/api/guardian/v1/status", self.status, methods=["GET"]),
            Route(
                "/api/guardian/v1/scheduling/start",
                self.start_scheduling,
                methods=["POST"],
            ),
            Route(
                "/api/guardian/v1/scheduling/stop",
                self.stop_scheduling,
                methods=["POST"],
            ),
            Route(
                "/api/guardian/v1/recovery/status",
                self.recovery_status,
                methods=["GET"],
            ),
            Route(
                "/api/guardian/v1/recovery/runs",
                self.submit_recovery,
                methods=["POST"],
            ),
            Route(
                "/api/guardian/v1/recovery/runs/{run_id:str}",
                self.recovery_run,
                methods=["GET"],
            ),
            Route("/api/guardian/v1/policy", self.policy, methods=["GET", "PATCH"]),
            Route("/api/guardian/v1/runs", self.runs, methods=["POST"]),
            Route(
                "/api/guardian/v1/runs/{run_id:str}/cancel",
                self.cancel_run,
                methods=["POST"],
            ),
            Route("/api/guardian/v1/syncs", self.sync, methods=["POST"]),
            Route("/api/guardian/v1/groups", self.groups, methods=["GET"]),
            Route(
                "/api/guardian/v1/groups/{group_id:str}/policy",
                self.group_policy,
                methods=["PATCH", "DELETE"],
            ),
            Route("/api/guardian/v1/channels", self.channels, methods=["GET"]),
            Route(
                "/api/guardian/v1/channels/{channel_id:str}",
                self.channel,
                methods=["GET", "PATCH"],
            ),
            Route(
                "/api/guardian/v1/channels/{channel_id:str}/actions",
                self.channel_action,
                methods=["POST"],
            ),
            Route("/api/guardian/v1/probe-spend", self.probe_spend, methods=["GET"]),
            Route("/api/guardian/v1/probe-budget", self.probe_budget, methods=["GET"]),
            Route("/api/guardian/v1/sampling/status", self.sampling_status, methods=["GET"]),
            Route(
                "/api/guardian/v1/channels/{channel_id:str}/explanation",
                self.channel_explanation,
                methods=["GET"],
            ),
            Route("/api/guardian/v1/events", self.events, methods=["GET"]),
        ]

    async def redirect_ui(self, _: Request) -> Response:
        return RedirectResponse("/guardian/", status_code=308)

    async def ui(self, _: Request) -> Response:
        index = _STATIC_ROOT / "index.html"
        if not index.is_file():
            # The console is a build artifact; in a source checkout that has not
            # run ``npm run build`` the page is simply absent.
            return PlainTextResponse(
                "The Guardian console has not been built. "
                "Run `npm run build` in web/, or use the REST API at "
                "/api/guardian/v1/.",
                status_code=503,
            )
        return FileResponse(index, media_type="text/html")

    async def asset(self, request: Request) -> Response:
        """Serve one file from the bundled console build.

        Vite emits a content-hashed tree under ``assets/``, so the path is
        resolved against the static root and rejected when it escapes.
        """

        relative = request.path_params["path"]
        candidate = (_STATIC_ROOT / "assets" / relative).resolve()
        assets_root = (_STATIC_ROOT / "assets").resolve()
        if not candidate.is_file() or assets_root not in candidate.parents:
            return JSONResponse({"error": "not_found"}, status_code=404)
        media_type = _MEDIA_TYPES.get(candidate.suffix.lower())
        if media_type is None:
            return JSONResponse({"error": "not_found"}, status_code=404)
        return FileResponse(
            candidate,
            media_type=media_type,
            # The filenames carry a content hash, so they are safe to cache.
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    async def session_state(self, request: Request) -> Response:
        """Report whether the caller already holds a valid console session."""

        request_id = self._request_id(request)
        if self._sessions is None:
            return JSONResponse(
                {
                    "ok": True,
                    "requestId": request_id,
                    "data": {"authenticated": False, "login_enabled": False},
                }
            )
        session = self._current_session(request)
        authenticated = session is not None
        token_present = (
            self._authenticator.authenticate(request.scope.get("headers", [])) is not None
        )
        return JSONResponse(
            {
                "ok": True,
                "requestId": request_id,
                "data": {
                    "authenticated": authenticated or token_present,
                    "login_enabled": True,
                    "username": session.username if session is not None else None,
                    "expires_at": (session.expires_at.isoformat() if session is not None else None),
                },
            },
            headers={"X-Request-ID": request_id, "Cache-Control": "no-store"},
        )

    async def login(self, request: Request) -> Response:
        """Exchange the console password for a signed session cookie."""

        request_id = self._request_id(request)
        if self._sessions is None:
            return self._error(
                request_id,
                ServiceError("LOGIN_DISABLED", "Console sign-in is not configured"),
                503,
            )
        body = await self._body(request)
        username = body.get("username")
        password = body.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            return self._error(
                request_id,
                ServiceError("VALIDATION_ERROR", "username and password are required"),
                422,
            )
        if len(username) > 128 or len(password) > 512:
            return self._error(
                request_id,
                ServiceError("VALIDATION_ERROR", "credentials are too long"),
                422,
            )
        if not self._throttle_login(request):
            return self._error(
                request_id,
                ServiceError("TOO_MANY_ATTEMPTS", "Too many sign-in attempts"),
                429,
            )
        if not self._sessions.check_credentials(username, password):
            await self._audit("console", "guardian_login", username[:64], "denied")
            return self._error(
                request_id,
                ServiceError("INVALID_CREDENTIALS", "Invalid username or password"),
                401,
            )
        token, session = self._sessions.issue(self._sessions.username)
        await self._audit("console", "guardian_login", self._sessions.username, "ok")
        response = JSONResponse(
            {
                "ok": True,
                "requestId": request_id,
                "data": {
                    "authenticated": True,
                    "username": session.username,
                    "expires_at": session.expires_at.isoformat(),
                },
            },
            headers={"X-Request-ID": request_id, "Cache-Control": "no-store"},
        )
        self._set_session_cookie(
            response, token, session.expires_at, secure=request.url.scheme == "https"
        )
        return response

    async def logout(self, request: Request) -> Response:
        """Clear the console session cookie."""

        request_id = self._request_id(request)
        response = JSONResponse(
            {"ok": True, "requestId": request_id, "data": {"authenticated": False}},
            headers={"X-Request-ID": request_id, "Cache-Control": "no-store"},
        )
        self._clear_session_cookie(response, secure=request.url.scheme == "https")
        return response

    async def overview(self, request: Request) -> Response:
        return await self._execute(request, "sub2api:read", self.service.overview)

    async def status(self, request: Request) -> Response:
        return await self._execute(request, "sub2api:read", self.service.status)

    async def start_scheduling(self, request: Request) -> Response:
        return await self._scheduling_control(request, enabled=True)

    async def stop_scheduling(self, request: Request) -> Response:
        return await self._scheduling_control(request, enabled=False)

    async def _scheduling_control(self, request: Request, *, enabled: bool) -> Response:
        async def control() -> dict[str, Any]:
            body = await self._body(request)
            confirm = body.get("confirm", False)
            if not isinstance(confirm, bool):
                raise ServiceError("VALIDATION_ERROR", "confirm must be a boolean")
            key = self._idempotency_key(request, required=True)
            assert key is not None
            return await self.service.set_scheduling_enabled(
                enabled=enabled,
                confirm=confirm,
                expected_revision=self._revision(request),
                idempotency_key=key,
            )

        return await self._execute(
            request,
            "sub2api:admin",
            control,
            mutation="guardian_set_scheduling",
        )

    async def recovery_status(self, request: Request) -> Response:
        return await self._execute(
            request,
            "sub2api:read",
            lambda: self.service.recovery_status(limit=self._limit(request, default=20)),
        )

    async def recovery_run(self, request: Request) -> Response:
        run_id = str(request.path_params["run_id"])
        return await self._execute(
            request,
            "sub2api:read",
            lambda: self.service.recovery_run(run_id),
        )

    async def submit_recovery(self, request: Request) -> Response:
        async def submit() -> dict[str, Any]:
            body = await self._body(request)
            confirm = body.get("confirm", False)
            if not isinstance(confirm, bool):
                raise ServiceError("VALIDATION_ERROR", "confirm must be a boolean")
            key = self._idempotency_key(request, required=True)
            assert key is not None
            return await self.service.submit_pending_recovery(
                confirm=confirm,
                idempotency_key=key,
            )

        return await self._execute(
            request,
            "sub2api:admin",
            submit,
            mutation="guardian_submit_recovery",
        )

    async def policy(self, request: Request) -> Response:
        if request.method == "GET":
            return await self._execute(request, "sub2api:read", self.service.get_policy)

        async def update() -> dict[str, Any]:
            body = await self._body(request)
            revision = self._revision(request)
            return await self.service.update_policy(body, expected_revision=revision)

        return await self._execute(
            request, "sub2api:admin", update, mutation="guardian_update_policy"
        )

    async def runs(self, request: Request) -> Response:
        async def run() -> dict[str, Any]:
            body = await self._body(request)
            dry_run = body.get("dry_run", True)
            if not isinstance(dry_run, bool):
                raise ServiceError("VALIDATION_ERROR", "dry_run must be a boolean")
            if not dry_run and body.get("confirm") is not True:
                raise ServiceError(
                    "CONFIRMATION_REQUIRED",
                    "A direct scheduling run requires confirm=true",
                )
            return await self.service.run_once(
                dry_run=dry_run,
                idempotency_key=self._idempotency_key(
                    request,
                    required=not dry_run,
                ),
            )

        return await self._execute(request, "sub2api:admin", run, mutation="guardian_run_once")

    async def cancel_run(self, request: Request) -> Response:
        run_id = request.path_params["run_id"]
        return await self._execute(
            request,
            "sub2api:admin",
            lambda: self.service.cancel_run(run_id),
            mutation="guardian_cancel_run",
            subject=run_id,
        )

    async def sync(self, request: Request) -> Response:
        async def synchronize() -> dict[str, Any]:
            await self._body(request)
            return await self.service.run_once(
                dry_run=True,
                idempotency_key=self._idempotency_key(request, required=False),
            )

        return await self._execute(request, "sub2api:admin", synchronize, mutation="guardian_sync")

    async def groups(self, request: Request) -> Response:
        return await self._execute(request, "sub2api:read", self.service.list_groups)

    async def group_policy(self, request: Request) -> Response:
        group_id = request.path_params["group_id"][:128]

        async def update() -> dict[str, Any]:
            body = await self._body(request)
            return await self.service.update_group_policy(group_id, body)

        action: Callable[[], Awaitable[dict[str, Any] | dict[str, bool]]]
        action = (
            update
            if request.method == "PATCH"
            else lambda: self.service.delete_group_policy(group_id)
        )
        return await self._execute(
            request,
            "sub2api:admin",
            action,
            mutation="guardian_group_policy",
            subject=group_id,
        )

    async def channels(self, request: Request) -> Response:
        async def listing() -> dict[str, Any]:
            return await self.service.list_channels(
                limit=self._limit(request, default=100),
                cursor=request.query_params.get("cursor"),
                group_id=request.query_params.get("group_id"),
                health=request.query_params.get("health"),
                query=request.query_params.get("query"),
            )

        return await self._execute(request, "sub2api:read", listing)

    async def channel(self, request: Request) -> Response:
        channel_id = request.path_params["channel_id"][:128]
        if request.method == "GET":
            return await self._execute(
                request,
                "sub2api:read",
                lambda: self.service.get_channel(channel_id),
            )

        async def update() -> dict[str, Any]:
            body = await self._body(request)
            control = body.pop("manual_control", None)
            actions = {
                "NONE": "resume",
                "PAUSED": "pause",
                "EXCLUDED": "exclude",
                "FUSED": "fuse",
            }
            result: dict[str, Any] | None = None
            if control is not None:
                if not isinstance(control, str) or control not in actions:
                    raise ServiceError("VALIDATION_ERROR", "manual_control is invalid")
                result = await self.service.channel_action(channel_id, actions[control])
            if body:
                result = await self.service.update_channel(channel_id, body)
            if result is None:
                raise ServiceError("VALIDATION_ERROR", "No channel fields were supplied")
            return result

        return await self._execute(
            request,
            "sub2api:admin",
            update,
            mutation="guardian_update_channel",
            subject=channel_id,
        )

    async def channel_action(self, request: Request) -> Response:
        channel_id = request.path_params["channel_id"][:128]

        async def action() -> dict[str, Any]:
            body = await self._body(request)
            name = body.get("action")
            if not isinstance(name, str):
                raise ServiceError("VALIDATION_ERROR", "action must be a string")
            return await self.service.channel_action(
                channel_id,
                name,
                idempotency_key=self._idempotency_key(request, required=False),
            )

        return await self._execute(
            request,
            "sub2api:admin",
            action,
            mutation="guardian_channel_action",
            subject=channel_id,
        )

    async def probe_spend(self, request: Request) -> Response:
        return await self._execute(request, "sub2api:read", self.service.probe_spend)

    async def probe_budget(self, request: Request) -> Response:
        return await self._execute(request, "sub2api:read", self.service.probe_budget)

    async def sampling_status(self, request: Request) -> Response:
        return await self._execute(request, "sub2api:read", self.service.sampling_status)

    async def channel_explanation(self, request: Request) -> Response:
        channel_id = request.path_params["channel_id"][:128]
        return await self._execute(
            request,
            "sub2api:read",
            lambda: self.service.channel_explanation(channel_id),
        )

    async def events(self, request: Request) -> Response:
        async def listing() -> dict[str, Any]:
            return await self.service.list_events(
                limit=self._limit(request, default=50),
                cursor=request.query_params.get("cursor"),
                event_type=request.query_params.get("event_type"),
                severity=request.query_params.get("severity"),
            )

        return await self._execute(request, "sub2api:read", listing)

    async def _execute(
        self,
        request: Request,
        scope: Scope,
        action: Callable[[], Awaitable[Any]],
        *,
        mutation: str | None = None,
        subject: str | None = None,
        require_idempotency: bool = False,
    ) -> Response:
        request_id = self._request_id(request)
        principal = self._authenticator.authenticate(request.scope.get("headers", []))
        if principal is None:
            # The console signs in with a cookie instead of an API key.  A
            # valid session is treated as an admin principal for every route
            # this API exposes, which is what the operator console needs.
            session = self._current_session(request)
            if session is not None:
                principal = Principal(
                    session.username, frozenset({"sub2api:read", "sub2api:write", "sub2api:admin"})
                )
        if principal is None:
            return self._error(
                request_id,
                ServiceError("UNAUTHENTICATED", "A valid API key is required"),
                401,
            )
        if not self._authorized(principal, scope):
            return self._error(
                request_id,
                ServiceError("FORBIDDEN", "The API key lacks the required scope"),
                403,
            )
        try:
            idempotency_key = (
                self._idempotency_key(request, required=require_idempotency) if mutation else None
            )
            with bind_principal(principal, request_id):
                if mutation and idempotency_key:
                    cached = await self.service.repository.get_idempotent_result(
                        idempotency_key, mutation, subject
                    )
                    if cached is not None:
                        return GuardianJSONResponse(
                            {"ok": True, "requestId": request_id, "data": cached},
                            headers={
                                "X-Request-ID": request_id,
                                "X-Idempotent-Replay": "true",
                            },
                        )
                data = await action()
                if mutation and idempotency_key and isinstance(data, dict):
                    await self.service.repository.save_idempotent_result(
                        idempotency_key,
                        mutation,
                        subject,
                        cast(dict[str, Any], data),
                    )
                if mutation:
                    await self._audit(principal.name, mutation, subject, "success")
            return GuardianJSONResponse(
                {"ok": True, "requestId": request_id, "data": data},
                headers={"X-Request-ID": request_id},
            )
        except ValidationError:
            error = ServiceError("VALIDATION_ERROR", "The request body is invalid")
            status_code = 422
        except ServiceError as exc:
            error = exc
            status_code = self._status_for(exc.code)
        except (json.JSONDecodeError, UnicodeError):
            error = ServiceError("VALIDATION_ERROR", "The request body is invalid")
            status_code = 422
        except Exception:
            self._logger.exception(
                "guardian_api_request_failed",
                extra={"requestId": request_id, "action": mutation or "read"},
            )
            error = ServiceError("INTERNAL_ERROR", "The Guardian service failed unexpectedly")
            status_code = 500
        if mutation:
            try:
                await self._audit(principal.name, mutation, subject, error.code)
            except Exception:
                self._logger.exception(
                    "guardian_api_audit_failed",
                    extra={"requestId": request_id, "action": mutation},
                )
        return self._error(request_id, error, status_code)

    def _current_session(self, request: Request) -> Session | None:
        """Return the console session carried by the request cookie, if valid."""

        if self._sessions is None:
            return None
        token = request.cookies.get(COOKIE_NAME, "")
        if not token:
            return None
        return self._sessions.verify(token)

    @staticmethod
    def _set_session_cookie(
        response: Response,
        token: str,
        expires_at: datetime,
        *,
        secure: bool,
    ) -> None:
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=max(0, int((expires_at - datetime.now(UTC)).total_seconds())),
            # HttpOnly keeps the token away from page scripts; SameSite=Lax
            # still allows the top-level navigation that loads the console.
            httponly=True,
            secure=secure,
            samesite="lax",
            path="/",
        )

    @staticmethod
    def _clear_session_cookie(response: Response, *, secure: bool) -> None:
        response.delete_cookie(
            COOKIE_NAME,
            httponly=True,
            secure=secure,
            samesite="lax",
            path="/",
        )

    def _throttle_login(self, request: Request) -> bool:
        """Allow a small number of sign-in attempts per client per minute.

        The window is short and held in process, which is enough to blunt
        password guessing without adding a store dependency to the login path.
        """

        client = request.client.host if request.client is not None else "unknown"
        now = datetime.now(UTC)
        window = self._login_attempts.setdefault(client, [])
        # Drop attempts that have aged out of the window.
        cutoff = now.timestamp() - 60
        while window and window[0] < cutoff:
            window.pop(0)
        if len(window) >= 10:
            return False
        window.append(now.timestamp())
        return True

    @staticmethod
    def _authorized(principal: Principal, scope: Scope) -> bool:
        return "sub2api:admin" in principal.scopes or scope in principal.scopes

    @staticmethod
    def _status_for(code: str) -> int:
        if code in {"POLICY_REVISION_CONFLICT"}:
            return 409
        if code.endswith("_NOT_FOUND"):
            return 404
        if code in {"POLICY_REVISION_REQUIRED"}:
            return 428
        if code == "REQUEST_TOO_LARGE":
            return 413
        if code in {"VALIDATION_ERROR", "INVALID_PAGE_SIZE", "INVALID_CURSOR"}:
            return 422
        return 409

    @staticmethod
    async def _body(request: Request) -> dict[str, Any]:
        raw = await request.body()
        if len(raw) > 64 * 1024:
            raise ServiceError("REQUEST_TOO_LARGE", "The request body is too large")
        if not raw:
            return {}
        value: object = json.loads(raw)
        if not isinstance(value, dict):
            raise ServiceError("VALIDATION_ERROR", "The request body must be an object")
        return dict(cast(dict[str, Any], value))

    @staticmethod
    def _revision(request: Request) -> int:
        supplied = request.headers.get("if-match", "").strip().strip('"')
        if not supplied:
            raise ServiceError("POLICY_REVISION_REQUIRED", "If-Match policy revision is required")
        try:
            revision = int(supplied)
        except ValueError as exc:
            raise ServiceError("VALIDATION_ERROR", "If-Match policy revision is invalid") from exc
        if revision < 1:
            raise ServiceError("VALIDATION_ERROR", "If-Match revision is invalid")
        return revision

    @staticmethod
    def _idempotency_key(request: Request, *, required: bool) -> str | None:
        supplied = request.headers.get("idempotency-key", "").strip()
        if not supplied and not required:
            return None
        if not _IDEMPOTENCY_KEY.fullmatch(supplied):
            raise ServiceError("VALIDATION_ERROR", "Idempotency-Key is missing or invalid")
        return supplied

    @staticmethod
    def _limit(request: Request, *, default: int) -> int:
        supplied = request.query_params.get("limit")
        if supplied is None:
            return default
        try:
            return int(supplied)
        except ValueError as exc:
            raise ServiceError("VALIDATION_ERROR", "limit must be an integer") from exc

    @staticmethod
    def _request_id(request: Request) -> str:
        supplied = request.headers.get("x-request-id", "").strip()
        if re.fullmatch(r"[A-Za-z0-9._-]{8,128}", supplied):
            return supplied
        return str(uuid.uuid4())

    @staticmethod
    def _error(request_id: str, error: ServiceError, status_code: int) -> JSONResponse:
        return JSONResponse(
            {
                "ok": False,
                "requestId": request_id,
                "error": {
                    "code": error.code,
                    "message": error.safe_message,
                    "retryable": error.retryable,
                },
            },
            status_code=status_code,
            headers={"X-Request-ID": request_id, "Cache-Control": "no-store"},
        )
