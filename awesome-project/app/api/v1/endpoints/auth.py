from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.v1 import API_PREFIX
from app.core.config import get_settings
from app.core.security import (
    clear_session_cookie,
    create_access_token,
    require_current_user,
    set_session_cookie,
)
from app.database.database import get_db
from app.models.user import User
from app.schemas.requests.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    SetPasswordRequest,
)
from app.schemas.responses.auth import (
    CurrentUserResponse,
    LoginResponse,
    MeResponse,
    MessageResponse,
)
from app.schemas.responses.envelope import envelope
from app.services.auth_service import AuthError, AuthService, PasswordWeak
from app.services.rbac import permissions_for

router = APIRouter(prefix="/auth", tags=["Auth"])


def _current_payload(user: User, db: Session) -> CurrentUserResponse:
    svc = AuthService(db)
    return CurrentUserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        phone=user.phone,
        role=user.role,
        created_at=user.created_at,
        inspection_count=svc.inspection_count(user.id),
        has_password=user.password_hash is not None,
    )


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and sign in",
)
def register(
    data: RegisterRequest, response: Response, db: Session = Depends(get_db)
):
    svc = AuthService(db)
    try:
        user = svc.register(data)
    except PasswordWeak as e:
        raise HTTPException(
            status_code=422,
            detail=f"Password {' and '.join(e.problems)}.",
        )
    except AuthError as e:
        raise HTTPException(status_code=409, detail=str(e))

    settings = get_settings()
    token = create_access_token(user)
    set_session_cookie(response, token, expires_hours=settings.jwt_expires_hours)
    response.headers["Location"] = f"{API_PREFIX}/auth/me"
    return envelope(
        LoginResponse(
            user=_current_payload(user, db),
            expires_in_hours=settings.jwt_expires_hours,
        ).model_dump(mode="json"),
        links={"self": f"{API_PREFIX}/auth/me"},
    )


@router.post("/login", summary="Sign in")
def login(
    data: LoginRequest, response: Response, db: Session = Depends(get_db)
):
    try:
        user = AuthService(db).authenticate(data.email, data.password)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))

    settings = get_settings()
    token = create_access_token(user)
    set_session_cookie(response, token, expires_hours=settings.jwt_expires_hours)
    return envelope(
        LoginResponse(
            user=_current_payload(user, db),
            expires_in_hours=settings.jwt_expires_hours,
        ).model_dump(mode="json"),
        links={"self": f"{API_PREFIX}/auth/me"},
    )


@router.post("/logout", summary="Sign out")
def logout(response: Response):
    clear_session_cookie(response)
    return envelope(MessageResponse(detail="Signed out").model_dump(mode="json"))


@router.get(
    "/me",
    summary="The signed-in user and their permissions (portal bootstrap)",
)
def me(user: User = Depends(require_current_user), db: Session = Depends(get_db)):
    """Called on page load. A 401 here is how the portal knows to show the
    sign-in screen rather than the dashboard.

    The permission list drives which controls the UI renders.
    """
    return envelope(
        MeResponse(
            user=_current_payload(user, db),
            permissions=permissions_for(user),
            is_admin=user.role == "admin",
        ).model_dump(mode="json"),
        links={"self": f"{API_PREFIX}/auth/me"},
    )


@router.post(
    "/set-password",
    summary="Set a password on an account that has none",
)
def set_password(
    payload: SetPasswordRequest,
    response: Response,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """Bootstrap for the pre-portal accounts, which have no password yet."""
    if user.password_hash is not None:
        raise HTTPException(
            status_code=400,
            detail="This account already has a password. Use change-password.",
        )
    new_password = payload.password

    try:
        AuthService(db).set_password(user, new_password)
    except PasswordWeak as e:
        raise HTTPException(
            status_code=422, detail=f"Password {' and '.join(e.problems)}."
        )

    settings = get_settings()
    set_session_cookie(
        response,
        create_access_token(user),
        expires_hours=settings.jwt_expires_hours,
    )
    return envelope(MessageResponse(detail="Password set").model_dump(mode="json"))


@router.post(
    "/change-password", summary="Change your password"
)
def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    try:
        AuthService(db).change_password(
            user, payload.current_password, payload.new_password
        )
    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PasswordWeak as e:
        raise HTTPException(
            status_code=422, detail=f"Password {' and '.join(e.problems)}."
        )
    return envelope(
        MessageResponse(detail="Password updated").model_dump(mode="json")
    )
