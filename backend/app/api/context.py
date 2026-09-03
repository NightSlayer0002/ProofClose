from dataclasses import dataclass

from fastapi import Header, HTTPException, Request


@dataclass(frozen=True)
class RequestContext:
    tenant_id: str
    actor_id: str
    identity_mode: str = "INSECURE_DEMO_CONTEXT"


def demo_context(
    request: Request,
    x_tenant_id: str | None = Header(default=None),
    x_actor_id: str | None = Header(default=None),
) -> RequestContext:
    settings = request.app.state.settings
    if not settings.demo_mode:
        raise HTTPException(status_code=401, detail={"code": "PRODUCTION_AUTH_REQUIRED", "message": "Production authentication is not configured."})
    tenant_id = x_tenant_id or settings.demo_tenant_id
    actor_id = x_actor_id or settings.demo_actor_id
    if tenant_id != settings.demo_tenant_id:
        raise HTTPException(status_code=403, detail={"code": "DEMO_TENANT_NOT_ALLOWED", "message": "The demo context is fixed to its synthetic merchant."})
    if actor_id != settings.demo_actor_id:
        raise HTTPException(status_code=403, detail={"code": "DEMO_ACTOR_NOT_ALLOWED", "message": "The demo context is fixed to its synthetic operator."})
    return RequestContext(tenant_id, actor_id)

