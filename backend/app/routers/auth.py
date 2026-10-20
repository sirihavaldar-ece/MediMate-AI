from secrets import token_urlsafe
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import PERSISTENT_SESSION_DAYS, SESSION_COOKIE_SAMESITE, SESSION_COOKIE_SECURE
from app.database import get_db
from app.models import CaregiverRelationship, User
from app.rate_limit import limiter
from app.schemas import (
    LinkCaregiverRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.security import (
    bearer_scheme,
    create_access_token,
    get_current_user,
    hash_password,
    require_role,
    revoke_access_token,
    validate_timezone,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["authentication"])
Database = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post("/register", response_model=TokenResponse, status_code=201)
@limiter.limit("10/minute")
def register(request: Request, payload: RegisterRequest, response: Response, database: Database) -> TokenResponse:
    email = str(payload.email).lower()
    if database.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    if not validate_timezone(payload.timezone):
        raise HTTPException(status_code=422, detail="Choose a valid time zone, such as Europe/London.")

    user = User(
        name=payload.name.strip(),
        email=email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        timezone=payload.timezone,
    )
    database.add(user)
    database.commit()
    database.refresh(user)
    token = create_access_token(user, remember_me=payload.remember_me)
    max_age = 60 * 60 * 24 * PERSISTENT_SESSION_DAYS if payload.remember_me else 60 * 60 * 24
    set_session_cookies(response, token, max_age)
    return auth_response(request, token, user)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
def login(request: Request, payload: LoginRequest, response: Response, database: Database) -> TokenResponse:
    email = str(payload.email).lower()
    user = database.query(User).filter(func.lower(User.email) == email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    token = create_access_token(user, remember_me=payload.remember_me)
    max_age = 60 * 60 * 24 * PERSISTENT_SESSION_DAYS if payload.remember_me else 60 * 60 * 24
    set_session_cookies(response, token, max_age)
    return auth_response(request, token, user)


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    _user: CurrentUser,
    database: Database,
) -> Response:
    token = credentials.credentials if credentials else request.cookies.get("medimate_session")
    if token:
        revoke_access_token(token, database)
    response.delete_cookie("medimate_session", path="/", secure=SESSION_COOKIE_SECURE, httponly=True, samesite=SESSION_COOKIE_SAMESITE)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


def set_session_cookies(response: Response, token: str, max_age: int) -> None:
    response.set_cookie("medimate_session", token, httponly=True, secure=SESSION_COOKIE_SECURE, samesite=SESSION_COOKIE_SAMESITE, max_age=max_age, path="/")
    response.set_cookie("medimate_csrf", token_urlsafe(32), httponly=False, secure=SESSION_COOKIE_SECURE, samesite=SESSION_COOKIE_SAMESITE, max_age=max_age, path="/")


def auth_response(request: Request, token: str, user: User) -> TokenResponse:
    # Browser callers use the HttpOnly cookie and never receive a JS-readable token.
    expose_token = request.headers.get("X-Auth-Mode") != "cookie"
    return TokenResponse(access_token=token if expose_token else None, user=user)


@router.get("/invitation", response_model=dict[str, str])
def invitation(user: CurrentUser) -> dict[str, str]:
    require_role(user, "patient")
    return {"invitation_code": user.invitation_code}


@router.post("/caregivers/link", status_code=201)
def link_caregiver(
    payload: LinkCaregiverRequest,
    user: CurrentUser,
    database: Database,
) -> dict[str, str]:
    require_role(user, "caregiver")
    patient = (
        database.query(User)
        .filter(func.lower(User.email) == str(payload.patient_email).lower())
        .first()
    )
    if (
        patient is None
        or patient.role != "patient"
        or patient.invitation_code != payload.invitation_code
    ):
        raise HTTPException(status_code=404, detail="Patient invitation could not be verified.")
    if patient.id == user.id:
        raise HTTPException(status_code=400, detail="You cannot link an account to itself.")
    existing = (
        database.query(CaregiverRelationship)
        .filter_by(patient_id=patient.id, caregiver_id=user.id)
        .first()
    )
    if existing is not None and existing.active:
        return {"status": "already_linked"}
    if existing is None:
        existing = CaregiverRelationship(
            patient_id=patient.id, caregiver_id=user.id, label=payload.label.strip()
        )
        database.add(existing)
    else:
        existing.active = True
        existing.label = payload.label.strip()
    patient.invitation_code = token_urlsafe(12)
    database.commit()
    return {"status": "linked"}


@router.delete("/caregivers/{caregiver_id}", status_code=204)
def unlink_caregiver(
    caregiver_id: int,
    user: CurrentUser,
    database: Database,
) -> None:
    require_role(user, "patient")
    relationship = (
        database.query(CaregiverRelationship)
        .filter_by(patient_id=user.id, caregiver_id=caregiver_id, active=True)
        .first()
    )
    if relationship is None:
        raise HTTPException(status_code=404, detail="Caregiver relationship not found.")
    relationship.active = False
    database.commit()
