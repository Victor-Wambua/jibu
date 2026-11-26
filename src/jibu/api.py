"""FastAPI application: chat, health, admin queue, feedback, widget, WhatsApp webhook."""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from . import __version__
from .config import Settings
from .kb import KBError, KnowledgeBase, load_kb_dir
from .ratelimit import RateLimiter
from .service import JibuService, UnknownKB
from .whatsapp import Sender, WhatsAppAdapter, verify_challenge

WEB_DIR = Path(__file__).parent / "web"
SessionId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_\-]{8,64}$")]
KbId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9\-]{1,62}$")]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=500)
    session_id: SessionId | None = None
    kb: KbId | None = None
    lang: Literal["en", "sw"] | None = None

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be blank")
        return v


class Suggestion(BaseModel):
    entry_id: str
    question: str


class Contact(BaseModel):
    phone: str | None
    whatsapp: str | None
    hours: str | None


class ChatResponse(BaseModel):
    reply_id: str
    session_id: str
    kb: str
    status: Literal["answered", "handoff", "smalltalk"]
    answer: str
    language: Literal["en", "sw"]
    detected_language: Literal["en", "sw", "mixed", "und"]
    confidence: float
    entry_id: str | None
    used_context: bool
    suggestions: list[Suggestion]
    handoff: Contact | None
    unanswered_id: str | None


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reply_id: str = Field(pattern=r"^r_[A-Za-z0-9_\-]{6,40}$")
    helpful: bool


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unanswered_id: str = Field(pattern=r"^u_[0-9a-f]{8}$")
    resolution: Literal["added_to_kb", "answered_manually", "out_of_scope", "duplicate"]
    entry_id: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=200)


def client_ip(request: Request, trust_proxy: bool) -> str:
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]  # the address appended by our own proxy, not a client-supplied one
    return request.client.host if request.client else "unknown"


def create_app(
    settings: Settings | None = None,
    kbs: dict[str, KnowledgeBase] | None = None,
    wa_sender: Sender | None = None,
    rate_clock: Callable[[], float] | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    if kbs is None:
        kbs = load_kb_dir(settings.kb_dir)
    service = JibuService(kbs, settings)
    limit, window = settings.rate_limit
    limiter = RateLimiter(limit, window, rate_clock) if rate_clock else RateLimiter(limit, window)
    adapter = WhatsAppAdapter(service, settings, wa_sender)

    app = FastAPI(
        title="Jibu",
        version=__version__,
        description="Answers from an approved knowledge base, or a handoff to a human.",
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.service = service
    app.state.whatsapp = adapter
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "Authorization"],
            allow_credentials=False,
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable) -> Response:  # type: ignore[type-arg]
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path == "/":
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
            )
            response.headers["X-Frame-Options"] = "DENY"
        return response

    def rate_limit(request: Request) -> None:
        ok, retry = limiter.check(client_ip(request, settings.trust_proxy))
        if not ok:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please wait a moment and try again.",
                headers={"Retry-After": str(max(1, round(retry)))},
            )

    def require_admin(authorization: Annotated[str | None, Header()] = None) -> None:
        token = settings.admin_token
        if not token:
            raise HTTPException(503, "Admin endpoints are disabled: set JIBU_ADMIN_TOKEN.")
        supplied = (
            authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
        )
        if not hmac.compare_digest(supplied.encode(), token.encode()):
            raise HTTPException(
                401, "Invalid or missing admin token.", headers={"WWW-Authenticate": "Bearer"}
            )

    # ------------------------------------------------------------------ public
    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "version": __version__,
            "knowledge_bases": [
                {"id": k.id, "name": k.organisation.name, "entries": len(k.entries)}
                for k in kbs.values()
            ],
        }

    @app.get("/meta")
    def meta(kb: KbId | None = None) -> dict[str, object]:
        try:
            engine = service.engine(kb)
        except UnknownKB:
            raise HTTPException(404, "Unknown knowledge base.") from None
        org = engine.kb.organisation
        hours = org.contact.hours
        return {
            "kb": org.id,
            "name": org.name,
            "threshold": engine.threshold,
            "welcome": {"en": org.welcome.en, "sw": org.welcome.sw},
            "starters": {
                lang: [{"entry_id": i, "question": q} for i, q in engine.starters(lang)]
                for lang in ("en", "sw")
            },
            "contact": {
                "phone": org.contact.phone,
                "whatsapp": org.contact.whatsapp,
                "hours": {"en": hours.en, "sw": hours.sw} if hours else None,
            },
        }

    @app.post("/chat", response_model=ChatResponse, dependencies=[Depends(rate_limit)])
    def chat(body: ChatRequest) -> ChatResponse:
        session_id = body.session_id or secrets.token_urlsafe(12)
        try:
            result = service.chat(body.message, f"web:{session_id}", body.kb, body.lang)
        except UnknownKB:
            raise HTTPException(404, "Unknown knowledge base.") from None
        r = result.reply
        org = service.kbs[result.kb].organisation
        handoff = None
        if r.status == "handoff":
            hours = org.contact.hours
            handoff = Contact(
                phone=org.contact.phone,
                whatsapp=org.contact.whatsapp,
                hours=hours.get(r.language) if hours else None,
            )
        return ChatResponse(
            reply_id=result.reply_id,
            session_id=session_id,
            kb=result.kb,
            status=r.status,
            answer=r.text,
            language=r.language,
            detected_language=r.detected,
            confidence=round(r.confidence, 3),
            entry_id=r.entry_id,
            used_context=r.used_context,
            suggestions=[Suggestion(entry_id=i, question=q) for i, q in r.suggestions],
            handoff=handoff,
            unanswered_id=result.unanswered_id,
        )

    @app.post("/feedback", dependencies=[Depends(rate_limit)])
    def feedback(body: FeedbackRequest) -> dict[str, bool]:
        if not service.record_feedback(body.reply_id, body.helpful):
            raise HTTPException(404, "Unknown or expired reply_id.")
        return {"recorded": True}

    # ------------------------------------------------------------------- admin
    @app.get("/admin/unanswered", dependencies=[Depends(require_admin)])
    def admin_unanswered(
        status: Literal["open", "resolved", "all"] = "open",
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> dict[str, object]:
        items = service.unanswered.list(None if status == "all" else status, limit)
        return {
            "stores_text": service.unanswered.capture_text,
            "count": len(items),
            "items": [i.__dict__ for i in items],
            "feedback": service.feedback_counts,
        }

    @app.post("/admin/feedback", dependencies=[Depends(require_admin)])
    def admin_feedback(body: ResolveRequest) -> dict[str, object]:
        item = service.unanswered.resolve(
            body.unanswered_id, body.resolution, body.entry_id, body.note
        )
        if item is None:
            raise HTTPException(404, "No such unanswered item.")
        return {"resolved": True, "item": item.__dict__}

    # ---------------------------------------------------------------- whatsapp
    @app.get("/webhooks/whatsapp")
    def wa_verify(
        mode: Annotated[str | None, Query(alias="hub.mode")] = None,
        token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
        challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
    ) -> Response:
        echoed = verify_challenge(settings.wa_verify_token, mode, token, challenge)
        if echoed is None:
            return PlainTextResponse("Forbidden", status_code=403)
        return PlainTextResponse(echoed)

    @app.post("/webhooks/whatsapp")
    async def wa_receive(
        request: Request, x_hub_signature_256: Annotated[str | None, Header()] = None
    ) -> Response:
        body = await request.body()
        if len(body) > 256_000:
            return JSONResponse({"error": "payload too large"}, status_code=413)
        status, result = adapter.handle(body, x_hub_signature_256)
        if status == 200 and result is not None:
            return JSONResponse(
                {
                    "processed": result.processed,
                    "duplicates": result.duplicates,
                    "ignored": result.ignored,
                }
            )
        messages = {
            403: "invalid signature",
            400: "invalid JSON",
            503: "WhatsApp webhook not configured",
        }
        return JSONResponse({"error": messages.get(status, "error")}, status_code=status)

    # ------------------------------------------------------------- static files
    @app.get("/widget.js", include_in_schema=False)
    def widget() -> FileResponse:
        return FileResponse(WEB_DIR / "jibu-widget.js", media_type="text/javascript")

    @app.get("/", include_in_schema=False)
    def demo() -> FileResponse:
        return FileResponse(WEB_DIR / "demo.html", media_type="text/html")

    @app.get("/demo.js", include_in_schema=False)
    def demo_js() -> FileResponse:
        return FileResponse(WEB_DIR / "demo.js", media_type="text/javascript")

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(WEB_DIR / "favicon.svg", media_type="image/svg+xml")

    return app


def app_from_env() -> FastAPI:
    """Factory for ``uvicorn jibu.api:app_from_env --factory``."""
    try:
        return create_app()
    except KBError as exc:
        raise SystemExit(f"Knowledge base is invalid:\n{exc}") from exc
