import hashlib
import hmac
import re
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Paste
from app.schemas import PasteCreate, PasteCreated, PastePatch, PasteRead

router = APIRouter(prefix="/pastes", tags=["pastes"])
SessionDep = Annotated[Session, Depends(get_session)]
MAX_ID_ATTEMPTS = 5
bearer = HTTPBearer(auto_error=False)


def require_management_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    if credentials is None or re.fullmatch(
        r"[A-Za-z0-9._~+/-]+=*", credentials.credentials
    ) is None:
        raise HTTPException(
            status_code=401,
            detail="A valid Bearer management key is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


ManagementKeyDep = Annotated[str, Depends(require_management_key)]


def get_managed_paste(paste_id: str, management_key: str, session: Session) -> Paste:
    paste = session.get(Paste, paste_id)
    if paste is None:
        raise HTTPException(status_code=404, detail="Paste not found")
    if paste.management_key_hash is None:
        raise HTTPException(
            status_code=403, detail="This legacy paste has no management key"
        )
    supplied_hash = hashlib.sha256(management_key.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(paste.management_key_hash, supplied_hash):
        raise HTTPException(status_code=403, detail="Invalid management key")
    return paste


@router.post("", response_model=PasteCreated, status_code=status.HTTP_201_CREATED)
def create_paste(
    payload: PasteCreate, response: Response, session: SessionDep
) -> PasteCreated:
    management_key = secrets.token_hex(32)
    key_hash = hashlib.sha256(management_key.encode("utf-8")).hexdigest()
    for _ in range(MAX_ID_ATTEMPTS):
        paste = Paste(
            id=secrets.token_urlsafe(16), content=payload.content,
            title=payload.title, language=payload.language,
            management_key_hash=key_hash,
        )
        session.add(paste)
        try:
            # PostgreSQL returns created_at via INSERT ... RETURNING.
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            if (
                isinstance(exc.orig, UniqueViolation)
                and exc.orig.diag.constraint_name == "pastes_pkey"
            ):
                continue
            raise
        response.headers["Location"] = f"/pastes/{paste.id}"
        response.headers["Cache-Control"] = "no-store"
        return PasteCreated(
            id=paste.id, created_at=paste.created_at,
            title=paste.title, language=paste.language,
            management_key=management_key,
        )
    raise HTTPException(status_code=503, detail="Could not allocate a paste ID")


@router.get("/{paste_id}", response_model=PasteRead)
def get_paste(paste_id: str, session: SessionDep) -> Paste:
    paste = session.get(Paste, paste_id)
    if paste is None:
        raise HTTPException(status_code=404, detail="Paste not found")
    return paste


@router.patch("/{paste_id}", response_model=PasteRead)
def update_paste(
    paste_id: str, payload: PastePatch, management_key: ManagementKeyDep,
    session: SessionDep,
) -> Paste:
    paste = get_managed_paste(paste_id, management_key, session)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(paste, field, value)
    session.commit()
    return paste


@router.delete("/{paste_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_paste(
    paste_id: str, management_key: ManagementKeyDep, session: SessionDep,
) -> Response:
    paste = get_managed_paste(paste_id, management_key, session)
    session.delete(paste)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
