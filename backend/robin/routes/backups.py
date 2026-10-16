import base64
import binascii

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from robin import auth, backups, db, grabs
from robin.routes import common

router = APIRouter(prefix="/api/backups", tags=["backups"])

# The setup steps a restore is offered at: its own, the first.
RESTORE_STEPS = frozenset({"", "restore"})


@router.get("")
def list_backups() -> list[backups.Backup]:
    return backups.listing()


@router.post("", status_code=201)
def back_up_now() -> backups.Backup:
    try:
        return backups.write(db.get_settings())
    except backups.BackupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{name}")
def download(name: str) -> FileResponse:
    try:
        path = backups.path_of(name)
    except backups.BackupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="application/octet-stream", filename=name)


@router.delete("/{name}", status_code=204)
def delete(name: str) -> None:
    try:
        backups.path_of(name).unlink()
    except backups.BackupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class RestoreIn(BaseModel):
    """A backup in the folder by `name`, or one uploaded as `data`, base64."""

    name: str | None = None
    data: str | None = Field(default=None, max_length=auth.MAX_RESTORE)
    passphrase: str = Field(min_length=1, max_length=200)


@router.post("/restore", status_code=204)
def restore(body: RestoreIn, response: Response, background: BackgroundTasks) -> None:
    """Only on a fresh install, at setup's first step. Signs out, the backup's account signs
    in from then on."""
    if db.get_account()["setup_step"] not in RESTORE_STEPS:
        raise HTTPException(status_code=409, detail="Restore is only offered in setup")
    try:
        if body.data is not None:
            blob = base64.b64decode(body.data, validate=True)
        elif body.name is not None:
            blob = backups.path_of(body.name).read_bytes()
        else:
            raise HTTPException(status_code=422, detail="Pick a backup")
        backups.restore(blob, body.passphrase)
    except binascii.Error as exc:
        raise HTTPException(status_code=422, detail="Not a Robin backup") from exc
    except backups.BackupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    response.delete_cookie(auth.COOKIE, path="/")
    background.add_task(common.notify_now, grabs.search_waiting, "restoring")
