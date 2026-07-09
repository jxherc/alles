import io
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from core.settings import data_dir

router = APIRouter(prefix="/api")

DATA_DIR: Path | None = None


def _data_dir() -> Path:
    return DATA_DIR or data_dir()


@router.get("/backup")
def export_backup():
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    fname = f"aide-backup-{ts}.zip"
    root = _data_dir()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # DB — flush the WAL into the main file first. we're WAL mode, so recent writes live in
        # aide.db-wal (which we don't ship); without a checkpoint the backed-up aide.db is missing
        # everything still sitting in the wal.
        db_path = root / "aide.db"
        if db_path.exists():
            try:
                from core.database import engine
                with engine.connect() as conn:
                    conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass  # best-effort; still ship whatever's on disk
            zf.write(db_path, "aide.db")
        # settings
        sj = root / "settings.json"
        if sj.exists():
            zf.write(sj, "settings.json")
        # at-rest encryption key — without it a restored DB can't decrypt
        # its API keys / mail passwords, so it travels with the backup
        sk = root / "secret.key"
        if sk.exists():
            zf.write(sk, "secret.key")
        # vapid key — push subscriptions in the DB are bound to it
        vp = root / "vapid.pem"
        if vp.exists():
            zf.write(vp, "vapid.pem")
        # uploads
        upload_dir = root / "uploads"
        if upload_dir.exists():
            for f in upload_dir.iterdir():
                if f.is_file():
                    zf.write(f, f"uploads/{f.name}")
        # gallery
        gallery_dir = root / "gallery"
        if gallery_dir.exists():
            for f in gallery_dir.iterdir():
                if f.is_file():
                    zf.write(f, f"gallery/{f.name}")
        # encrypted vault attachments — their .enc blobs live on disk, not in aide.db, so
        # without this a restore loses every secret attachment
        att_dir = root / "vault_attachments"
        if att_dir.exists():
            for f in att_dir.iterdir():
                if f.is_file():
                    zf.write(f, f"vault_attachments/{f.name}")
        # the markdown vault — notes + docs live here as files now, so a backup without it
        # loses every note. recurse (the vault has subfolders: Notes/, _assets/, etc.)
        vault_d = root / "vault"
        if vault_d.exists():
            for f in vault_d.rglob("*"):
                if f.is_file():
                    zf.write(f, f"vault/{f.relative_to(vault_d).as_posix()}")

    buf.seek(0)
    return StreamingResponse(
        iter([buf.read()]),
        media_type="application/zip",
        headers={"content-disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/backup/restore")
async def restore_backup(file: UploadFile = File(...)):
    content = await file.read()
    if not content:
        raise HTTPException(400, "empty file")
    root = _data_dir()

    # validate it's a zip with aide.db
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()
            if "aide.db" not in names:
                raise HTTPException(400, "not a valid aide backup (no aide.db)")

            # backup current data dir first
            backup_cur = (
                root.parent / f"aide-pre-restore-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            )
            if root.exists():
                shutil.copytree(root, backup_cur)

            # extract — refuse member paths that escape the data dir (zip-slip)
            data_root = root.resolve()
            for name in names:
                if name.endswith("/"):
                    continue
                dest = (root / name).resolve()
                if not dest.is_relative_to(data_root):
                    raise HTTPException(400, f"invalid path in archive: {name}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(name))

            # drop stale wal/shm sidecars from the pre-restore db — they don't belong to the
            # db we just wrote, and SQLite would otherwise replay the old wal onto it on reload
            if "aide.db" in names:
                for side in ("aide.db-wal", "aide.db-shm"):
                    if side not in names:
                        (root / side).unlink(missing_ok=True)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"restore failed: {e}")

    return {"ok": True, "message": "restore complete — please reload"}
