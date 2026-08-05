"""
Beast AI Trading Bot — Phase 13 Automated Encrypted DB Backup Engine
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

import config

logger = logging.getLogger("beast.backup")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class BackupEngine:
    """Creates timestamped encrypted archives of SQLite DB + portfolio logs."""

    def __init__(
        self,
        backup_dir: str | Path | None = None,
        retain: int | None = None,
    ) -> None:
        self.backup_dir = Path(backup_dir or getattr(config, "BACKUP_DIR", "backups"))
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.retain = int(retain or getattr(config, "BACKUP_RETAIN_COUNT", 14))
        self.interval_seconds = float(getattr(config, "BACKUP_INTERVAL_SECONDS", 86400))
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.last_backup: dict[str, Any] | None = None
        self.last_error: str | None = None

    def _fernet(self) -> Fernet:
        raw = os.getenv(getattr(config, "BACKUP_KEY_ENV", "BACKUP_KEY"), "").strip()
        if not raw:
            # Deterministic local key from JWT secret / fallback so backups are recoverable on same host
            seed = os.getenv(config.JWT_SECRET_ENV, "").strip() or "beast-local-backup-key"
            digest = hashlib.sha256(seed.encode("utf-8")).digest()
            raw = base64.urlsafe_b64encode(digest).decode("ascii")
        # Accept raw 32-url-safe-base64 Fernet keys or derive from passphrase
        try:
            return Fernet(raw.encode("utf-8") if isinstance(raw, str) else raw)
        except Exception:
            digest = hashlib.sha256(raw.encode("utf-8")).digest()
            return Fernet(base64.urlsafe_b64encode(digest))

    def _candidate_files(self) -> list[Path]:
        root = Path(".")
        names = [
            "beast_app.db",
            getattr(config, "PAPER_PORTFOLIO_PATH", "paper_portfolio.json"),
            getattr(config, "TRADE_HISTORY_CSV", "trade_history.csv"),
            getattr(config, "TRADE_HISTORY_JSON", "trade_history.json"),
            getattr(config, "COPY_LEDGER_PATH", "copy_trading_ledger.json"),
            getattr(config, "BILLING_STATE_PATH", "subscription_state.json"),
            getattr(config, "PAYMENTS_MOCK_LOG", "payments_mock_log.json"),
            getattr(config, "CMS_CONTENT_PATH", "content/cms_content.json"),
        ]
        files: list[Path] = []
        for name in names:
            path = Path(name)
            if not path.is_absolute():
                path = root / path
            if path.exists() and path.is_file():
                files.append(path)
        return files

    def create_backup(self) -> dict[str, Any]:
        stamp = _utc_stamp()
        files = self._candidate_files()
        if not files:
            raise RuntimeError("No backup source files found")

        with tempfile.TemporaryDirectory(prefix="beast-backup-") as tmp:
            tmp_path = Path(tmp)
            archive_path = tmp_path / f"beast_backup_{stamp}.tar.gz"
            with tarfile.open(archive_path, "w:gz") as tar:
                for file_path in files:
                    tar.add(file_path, arcname=file_path.name)

            encrypted_name = f"beast_backup_{stamp}.tar.gz.enc"
            dest = self.backup_dir / encrypted_name
            token = self._fernet().encrypt(archive_path.read_bytes())
            dest.write_bytes(token)

            manifest = {
                "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "file": encrypted_name,
                "path": str(dest.resolve()),
                "sources": [p.name for p in files],
                "bytes": dest.stat().st_size,
                "encrypted": True,
            }
            (self.backup_dir / f"beast_backup_{stamp}.json").write_text(
                json.dumps(manifest, indent=2),
                encoding="utf-8",
            )

        self._prune()
        self.last_backup = manifest
        self.last_error = None
        logger.info("Backup created: %s (%s bytes)", dest.name, manifest["bytes"])
        return manifest

    def _prune(self) -> None:
        enc_files = sorted(self.backup_dir.glob("beast_backup_*.tar.gz.enc"))
        excess = len(enc_files) - self.retain
        if excess <= 0:
            return
        for path in enc_files[:excess]:
            try:
                path.unlink(missing_ok=True)
                meta = path.with_suffix("").with_suffix(".json")  # rough
                # companion manifest: beast_backup_STAMP.json
                stamp = path.name.replace("beast_backup_", "").replace(".tar.gz.enc", "")
                companion = self.backup_dir / f"beast_backup_{stamp}.json"
                companion.unlink(missing_ok=True)
            except OSError:
                pass

    def status(self) -> dict[str, Any]:
        backups = sorted(self.backup_dir.glob("beast_backup_*.tar.gz.enc"), reverse=True)
        return {
            "backup_dir": str(self.backup_dir.resolve()),
            "count": len(backups),
            "retain": self.retain,
            "interval_seconds": self.interval_seconds,
            "last_backup": self.last_backup,
            "last_error": self.last_error,
            "latest_file": backups[0].name if backups else None,
        }

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="beast-backup-loop")

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        # Initial backup shortly after boot
        await asyncio.sleep(3)
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self.create_backup)
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                logger.warning("Backup failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue


backup_engine = BackupEngine()
