from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.config import ACCESS_TOKEN_MINUTES, PERSISTENT_SESSION_DAYS, SECRET_KEY
from app.database import get_db
from app.models import RevokedToken, User, utc_now

password_hasher = PasswordHash.recommended()
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_hasher.verify(password, password_hash)


def create_access_token(user: User, remember_me: bool = False) -> str:
    lifetime = timedelta(days=PERSISTENT_SESSION_DAYS) if remember_me else timedelta(minutes=ACCESS_TOKEN_MINUTES)
    expires_at = datetime.now(timezone.utc) + lifetime
    return jwt.encode(
        {"sub": str(user.id), "jti": uuid4().hex, "exp": expires_at},
        SECRET_KEY,
        algorithm="HS256",
    )


def validate_timezone(value: str) -> bool:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError:
        return False
    return True


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    request: Request,
    database: Annotated[Session, Depends(get_db)],
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sign in to access this resource.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = credentials.credentials if credentials else request.cookies.get("medimate_session")
    if token is None:
        raise unauthorized
    if credentials is None and request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf_cookie = request.cookies.get("medimate_csrf")
        csrf_header = request.headers.get("X-CSRF-Token")
        if not csrf_cookie or csrf_header != csrf_cookie:
            raise HTTPException(status_code=403, detail="Your session check failed. Refresh the page and try again.")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        user_id = int(payload["sub"])
        token_id = str(payload["jti"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized from None
    if database.query(RevokedToken.id).filter_by(token_id=token_id).first():
        raise unauthorized
    user = database.get(User, user_id)
    if user is None:
        raise unauthorized
    return user


def revoke_access_token(token: str, database: Session) -> None:
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    token_id = str(payload["jti"])
    expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    database.query(RevokedToken).filter(
        RevokedToken.expires_at <= utc_now()
    ).delete(synchronize_session=False)
    database.add(RevokedToken(token_id=token_id, expires_at=expires_at))
    database.commit()


def require_role(user: User, expected_role: str) -> None:
    if user.role != expected_role:
        raise HTTPException(status_code=403, detail="This action is not available for your account.")


def can_access_patient(database: Session, user: User, patient_id: int) -> bool:
    if user.role == "patient":
        return user.id == patient_id
    if user.role != "caregiver":
        return False
    from app.models import CaregiverRelationship

    relationship = (
        database.query(CaregiverRelationship)
        .filter_by(patient_id=patient_id, caregiver_id=user.id, active=True)
        .first()
    )
    return relationship is not None
