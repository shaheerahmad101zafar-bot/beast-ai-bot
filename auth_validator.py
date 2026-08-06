"""
API key safety audit helpers.
"""

from __future__ import annotations

from typing import Any


class AuthValidator:
    @staticmethod
    def audit(validation: dict[str, Any]) -> dict[str, Any]:
        permissions = validation.get("permissions") or {}
        withdraw_enabled = bool(
            validation.get("can_withdraw")
            or permissions.get("withdraw")
            or permissions.get("enableWithdrawals")
            or permissions.get("withdrawEnabled")
        )
        if withdraw_enabled:
            raise PermissionError(
                "Unsafe Binance API key rejected: withdrawal permission must be disabled."
            )
        return {
            "ok": True,
            "withdrawal_blocked": not withdraw_enabled,
            "permissions_source": permissions.get("source") or "unknown",
        }


auth_validator = AuthValidator()
