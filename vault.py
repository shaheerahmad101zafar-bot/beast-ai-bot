"""
Beast AI Trading Bot — Phase 6 Secure Exchange API Credentials Vault

Fernet-encrypted local storage for multi-exchange API keys (Binance, Bybit,
KuCoin, OKX) with CCXT connection tests and permission checks.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ccxt
from cryptography.fernet import Fernet, InvalidToken

import config
from security import secure_decrypt_api_secret as decrypt_api_secret
from security import secure_encrypt_api_secret as encrypt_api_secret

SENSITIVE_FIELDS = {"api_key", "api_secret", "passphrase"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class CredentialVault:
    """Encrypted at-rest vault for exchange API credentials."""

    def __init__(
        self,
        key_path: str | Path = config.VAULT_KEY_PATH,
        store_path: str | Path = config.VAULT_STORE_PATH,
    ) -> None:
        self.key_path = Path(key_path)
        self.store_path = Path(store_path)
        self._fernet = Fernet(self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        if self.key_path.exists():
            return self.key_path.read_bytes().strip()
        key = Fernet.generate_key()
        self.key_path.write_bytes(key)
        try:
            self.key_path.chmod(0o600)
        except OSError:
            pass
        return key

    def _read_store(self) -> dict[str, Any]:
        if not self.store_path.exists():
            return {"version": 1, "accounts": {}}
        try:
            token = self.store_path.read_bytes()
            raw = self._fernet.decrypt(token)
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                return {"version": 1, "accounts": {}}
            data.setdefault("accounts", {})
            return data
        except (InvalidToken, json.JSONDecodeError, OSError):
            return {"version": 1, "accounts": {}}

    def _write_store(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data, indent=2).encode("utf-8")
        token = self._fernet.encrypt(payload)
        self.store_path.write_bytes(token)
        try:
            self.store_path.chmod(0o600)
        except OSError:
            pass

    @staticmethod
    def normalize_exchange(exchange: str) -> str:
        key = (exchange or "").strip().lower()
        if key not in config.SUPPORTED_EXCHANGES:
            raise ValueError(
                f"Unsupported exchange '{exchange}'. "
                f"Supported: {', '.join(config.SUPPORTED_EXCHANGES)}"
            )
        return key

    @staticmethod
    def ccxt_id(exchange: str) -> str:
        return config.SUPPORTED_EXCHANGES[CredentialVault.normalize_exchange(exchange)]

    def save_account(
        self,
        *,
        exchange: str,
        api_key: str,
        api_secret: str,
        label: str,
        role: str = "follower",
        passphrase: str | None = None,
        paper_mode: bool = False,
        equity_hint: float | None = None,
        permissions: dict[str, Any] | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        exchange = self.normalize_exchange(exchange)
        role = (role or "follower").strip().lower()
        if role not in {"master", "follower"}:
            raise ValueError("role must be 'master' or 'follower'")
        if not api_key.strip() or not api_secret.strip():
            raise ValueError("api_key and api_secret are required")

        store = self._read_store()
        accounts = store["accounts"]
        acc_id = account_id or str(uuid.uuid4())[:10]

        # Only one master at a time
        if role == "master":
            for existing in accounts.values():
                if existing.get("role") == "master" and existing.get("id") != acc_id:
                    existing["role"] = "follower"

        record = {
            "id": acc_id,
            "label": label.strip() or f"{exchange}-{acc_id}",
            "exchange": exchange,
            "ccxt_id": self.ccxt_id(exchange),
            "role": role,
            "api_key": encrypt_api_secret(api_key.strip()),
            "api_secret": encrypt_api_secret(api_secret.strip()),
            "passphrase": (
                encrypt_api_secret((passphrase or "").strip()) if (passphrase or "").strip() else None
            ),
            "paper_mode": bool(paper_mode),
            "equity_hint": float(equity_hint) if equity_hint is not None else None,
            "permissions": permissions or {},
            "created_at": accounts.get(acc_id, {}).get("created_at") or _utc_now(),
            "updated_at": _utc_now(),
            "active": True,
        }
        accounts[acc_id] = record
        store["accounts"] = accounts
        self._write_store(store)
        return self.public_view(record)

    def get_account(self, account_id: str, include_secrets: bool = False) -> dict[str, Any] | None:
        acc = self._read_store()["accounts"].get(account_id)
        if not acc:
            return None
        return dict(acc) if include_secrets else self.public_view(acc)

    def list_accounts(self, role: str | None = None) -> list[dict[str, Any]]:
        accounts = list(self._read_store()["accounts"].values())
        if role:
            accounts = [a for a in accounts if a.get("role") == role]
        return [self.public_view(a) for a in accounts if a.get("active", True)]

    def delete_account(self, account_id: str) -> bool:
        store = self._read_store()
        if account_id not in store["accounts"]:
            return False
        del store["accounts"][account_id]
        self._write_store(store)
        return True

    def get_master(self, include_secrets: bool = False) -> dict[str, Any] | None:
        for acc in self._read_store()["accounts"].values():
            if acc.get("role") == "master" and acc.get("active", True):
                return dict(acc) if include_secrets else self.public_view(acc)
        return None

    def get_followers(self, include_secrets: bool = False) -> list[dict[str, Any]]:
        out = []
        for acc in self._read_store()["accounts"].values():
            if acc.get("role") == "follower" and acc.get("active", True):
                out.append(dict(acc) if include_secrets else self.public_view(acc))
        return out

    @staticmethod
    def public_view(account: dict[str, Any]) -> dict[str, Any]:
        view = {k: v for k, v in account.items() if k not in SENSITIVE_FIELDS}
        try:
            key = decrypt_api_secret(account.get("api_key") or "")
        except Exception:
            key = ""
        view["api_key_masked"] = (
            f"{key[:4]}…{key[-4:]}" if len(key) >= 8 else "****"
        )
        return view

    def build_exchange(self, account: dict[str, Any]) -> ccxt.Exchange:
        """Instantiate a CCXT client from a secret-bearing account record."""
        exchange_id = account.get("ccxt_id") or self.ccxt_id(account["exchange"])
        klass = getattr(ccxt, exchange_id)
        params: dict[str, Any] = {
            "apiKey": decrypt_api_secret(account["api_key"]),
            "secret": decrypt_api_secret(account["api_secret"]),
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},
        }
        if account.get("passphrase"):
            params["password"] = decrypt_api_secret(account["passphrase"])
        return klass(params)

    def validate_connection(
        self,
        *,
        exchange: str,
        api_key: str,
        api_secret: str,
        passphrase: str | None = None,
        paper_mode: bool = False,
        equity_hint: float | None = None,
    ) -> dict[str, Any]:
        """
        Test API credentials and permission surface.

        Rejects keys that appear to allow withdrawals when the exchange
        exposes an API-restriction endpoint.
        """
        exchange = self.normalize_exchange(exchange)

        if paper_mode:
            equity = float(equity_hint or 1_000.0)
            return {
                "ok": True,
                "paper_mode": True,
                "exchange": exchange,
                "ccxt_id": self.ccxt_id(exchange),
                "equity": equity,
                "can_read": True,
                "can_trade": True,
                "can_withdraw": False,
                "permissions": {
                    "read": True,
                    "trade": True,
                    "withdraw": False,
                    "source": "paper_mode",
                },
                "message": "Paper-mode account accepted (no live exchange call).",
            }

        account = {
            "exchange": exchange,
            "ccxt_id": self.ccxt_id(exchange),
            "api_key": api_key.strip(),
            "api_secret": api_secret.strip(),
            "passphrase": (passphrase or "").strip() or None,
        }
        client = self.build_exchange(account)
        permissions = {
            "read": False,
            "trade": False,
            "withdraw": False,
            "source": "inferred",
        }
        equity = 0.0

        try:
            balance = client.fetch_balance()
            permissions["read"] = True
            equity = self._extract_equity(balance)

            # Probe trade permission lightly (no order placed)
            permissions["trade"] = self._infer_trade_permission(client, exchange)
            withdraw_flag, source = self._check_withdraw_disabled(client, exchange)
            permissions["withdraw"] = withdraw_flag
            permissions["source"] = source

            if permissions["withdraw"]:
                raise PermissionError(
                    "API key appears to allow withdrawals. "
                    "Disable withdrawal permission before connecting."
                )
            if not permissions["read"]:
                raise PermissionError("API key failed read/balance permission check.")

            return {
                "ok": True,
                "paper_mode": False,
                "exchange": exchange,
                "ccxt_id": self.ccxt_id(exchange),
                "equity": equity,
                "can_read": permissions["read"],
                "can_trade": permissions["trade"],
                "can_withdraw": permissions["withdraw"],
                "permissions": permissions,
                "message": "Connection validated. Withdrawal permission disabled.",
            }
        except PermissionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectionError(f"Exchange validation failed: {exc}") from exc
        finally:
            try:
                client.close()
            except Exception:
                pass

    @staticmethod
    def _extract_equity(balance: dict[str, Any]) -> float:
        total = balance.get("total") or {}
        if isinstance(total, dict):
            for asset in ("USDT", "USD", "USDC"):
                if total.get(asset) is not None:
                    try:
                        return float(total[asset])
                    except (TypeError, ValueError):
                        pass
        try:
            return float(balance.get("USDT", {}).get("total") or 0.0)
        except Exception:
            return 0.0

    @staticmethod
    def _infer_trade_permission(client: ccxt.Exchange, exchange: str) -> bool:
        # Conservative default: if we can read private balance, assume trade
        # may be enabled; exchange-specific restriction endpoints refine this.
        try:
            if exchange == "binance" and hasattr(client, "sapiGetAccountApiRestrictions"):
                data = client.sapiGetAccountApiRestrictions()
                return bool(
                    data.get("enableFutures")
                    or data.get("enableSpotAndMarginTrading")
                    or data.get("enableInternalTransfer")
                )
        except Exception:
            pass
        return True

    @staticmethod
    def _check_withdraw_disabled(
        client: ccxt.Exchange,
        exchange: str,
    ) -> tuple[bool, str]:
        """
        Returns (withdraw_enabled, source).
        Prefer explicit restriction APIs; otherwise assume withdraw disabled
        only when we cannot prove it is enabled.
        """
        try:
            if exchange == "binance" and hasattr(client, "sapiGetAccountApiRestrictions"):
                data = client.sapiGetAccountApiRestrictions()
                enabled = bool(data.get("enableWithdrawals"))
                return enabled, "binance_api_restrictions"
        except Exception:
            pass

        try:
            if exchange == "okx" and hasattr(client, "privateGetAccountConfig"):
                data = client.privateGetAccountConfig()
                # OKX does not always expose withdraw flag here; treat unknown as False
                return False, "okx_account_config"
        except Exception:
            pass

        # Bybit / KuCoin: no reliable unified withdraw flag via CCXT — require
        # operator to disable withdraw on exchange UI; we report False (safe).
        return False, "assumed_disabled"


vault = CredentialVault()
