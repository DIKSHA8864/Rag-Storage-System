"""
Owner/Admin console vs End User portal, enforced at the API: every
owner/admin endpoint refuses an end-user token, and every end-user
endpoint refuses an owner token - checked for ALL routes automatically,
so a new endpoint that forgets its guard fails here.
"""

import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.api import storage_api
from app.security.auth import create_access_token, create_end_user_token, require_admin_key, require_end_user_key

ADMIN_GUARDS = {"require_admin_key", "require_owner_role"}
END_USER_GUARDS = {"require_end_user_key", "require_end_user_account", "current_matter"}
# Deliberately public: sign-in/sign-up, Stripe's signed webhook, and static HTML shells that hold no data.
PUBLIC = {
    "/", "/admin/dashboard", "/analyze", "/upload-test", "/auth/login", "/billing/stripe/webhook",
    "/end-user/auth/login", "/end-user/auth/signup/request-code", "/end-user/auth/signup/complete",
    "/end-user/auth/password-reset/request-code", "/end-user/auth/password-reset/complete",
}


def _dependency_names(dependant, out):
    for sub in dependant.dependencies:
        out.add(getattr(sub.call, "__name__", ""))
        _dependency_names(sub, out)
    return out


def _routes(routes, prefix="", inherited=frozenset()):
    for route in routes:
        if type(route).__name__ == "_IncludedRouter":  # FastAPI >= 0.140 keeps included routers nested
            router, context = route.original_router, route.include_context
            names = {getattr(d.dependency, "__name__", "") for d in router.dependencies}
            names |= {getattr(getattr(d, "dependency", d), "__name__", "") for d in (getattr(context, "dependencies", None) or [])}
            yield from _routes(router.routes, prefix + (getattr(context, "prefix", "") or ""), inherited | names)
        elif isinstance(route, APIRoute):
            names = _dependency_names(route.dependant, set()) | {getattr(d.dependency, "__name__", "") for d in route.dependencies}
            yield prefix + route.path, sorted(route.methods), names | inherited


ALL_ROUTES = list(_routes(storage_api.app.routes))


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


@pytest.fixture
def real_auth():
    """Undo conftest's auth bypass - these tests are about the real guards."""

    saved = dict(storage_api.app.dependency_overrides)
    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    storage_api.app.dependency_overrides.pop(require_end_user_key, None)
    yield TestClient(storage_api.app)
    storage_api.app.dependency_overrides.clear()
    storage_api.app.dependency_overrides.update(saved)


def test_every_route_is_guarded_or_deliberately_public():
    unguarded = [path for path, _, names in ALL_ROUTES if not names & (ADMIN_GUARDS | END_USER_GUARDS) and path not in PUBLIC]
    assert unguarded == []
    assert sum(1 for _, _, names in ALL_ROUTES if names & ADMIN_GUARDS) > 50  # the walk really saw the routers
    assert sum(1 for _, _, names in ALL_ROUTES if names & END_USER_GUARDS) > 10


def test_end_user_token_is_refused_on_every_owner_route(real_auth):
    token = create_end_user_token(end_user_id=1, email="client@example.com", tenant_id=1, session_version=0)
    admin_routes = [(path, methods) for path, methods, names in ALL_ROUTES if names & ADMIN_GUARDS]

    let_through = []
    for path, methods in admin_routes:
        for method in methods:
            response = real_auth.request(method, _concrete(path), headers={"Authorization": f"Bearer {token}"})
            if response.status_code not in (401, 403):
                let_through.append((method, path, response.status_code))
    assert let_through == []


def test_owner_token_is_refused_on_every_end_user_route(real_auth):
    token = create_access_token(owner_id=1, email="owner@example.com", tenant_id=1, role="owner")
    end_user_routes = [(path, methods) for path, methods, names in ALL_ROUTES if names & END_USER_GUARDS]

    let_through = []
    for path, methods in end_user_routes:
        for method in methods:
            response = real_auth.request(method, _concrete(path), headers={"Authorization": f"Bearer {token}"})
            if response.status_code not in (401, 403):
                let_through.append((method, path, response.status_code))
    assert let_through == []
