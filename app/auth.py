import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import get_settings

_security = HTTPBasic()


def verify_credentials(
    credentials: Annotated[HTTPBasicCredentials, Depends(_security)],
) -> str:
    settings = get_settings()
    user_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        settings.auth_username.encode("utf-8"),
    )
    pass_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        settings.auth_password.encode("utf-8"),
    )
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


CurrentUser = Annotated[str, Depends(verify_credentials)]
