from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr

from app.security.auth import (
    create_access_token,
    verify_password,
)
from app.security.owner_repository import (
    get_owner_by_email,
)


from fastapi import Request
from app.security.rate_limit import limiter

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class OwnerResponse(BaseModel):
    id: int
    email: EmailStr
    role: str


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
def login(request: Request, body: LoginRequest) -> LoginResponse:
    """Authenticate the Owner and return a JWT access token."""

    owner = get_owner_by_email(body.email)

    if owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not owner["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner account is disabled.",
        )

    if not verify_password(
        body.password,
        owner["password_hash"],
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    token = create_access_token(
        owner_id=owner["id"],
        email=owner["email"],
        tenant_id=owner.get("tenant_id", 1),
        role=owner["role"],
    )

    from config.settings import get_settings

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=get_settings().access_token_expire_minutes * 60,
    )