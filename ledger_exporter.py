"""
Trade history audit ledger exporter (CSV + lightweight PDF).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any

from bot_service import bot_service


class LedgerExporter:
    FIELDS: list[str] = [
        "timestamp",
        "pair",
        "direction",
        "entry_price",
        "exit_price",
        "size",
        "leverage",
        "fees_usd",
        "slippage_pct",
        "gross_pnl",
        "pnl_usd",
        "exit_reason",
        "ai_reasoning",
        "trade_id",
    ]

    def _rows(self) -> list[dict[str, Any]]:
        history = bot_service.get_trade_history(limit=5000).get("trades") or []
        rows: list[dict[str, Any]] = []
        for t in history:
            rows.append(
                {
                    "timestamp": t.get("timestamp") or "",
                    "pair": t.get("pair") or "",
                    "direction": t.get("direction") or "",
                    "entry_price": t.get("entry_price"),
                    "exit_price": t.get("exit_price"),
                    "size": t.get("size"),
                    "leverage": t.get("leverage"),
                    "fees_usd": t.get("fees_usd") or 0.0,
                    "slippage_pct": t.get("slippage_pct") or "",
                    "gross_pnl": t.get("gross_pnl") if t.get("gross_pnl") is not None else "",
                    "pnl_usd": t.get("pnl_usd"),
                    "exit_reason": t.get("exit_reason") or "",
                    "ai_reasoning": t.get("ai_reasoning") or "",
                    "trade_id": t.get("trade_id") or "",
                }
            )
        return rows

    def build_csv(self) -> str:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=self.FIELDS)
        writer.writeheader()
        for row in self._rows():
            writer.writerow(row)
        return buf.getvalue()

    def build_pdf(self) -> bytes:
        """Minimal PDF 1.4 text ledger (no external PDF dependency)."""
        rows = self._rows()
        generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        lines = [
            "Beast AI Trading Desk — Trade Audit Ledger",
            f"Generated: {generated}",
            f"Closed trades: {len(rows)}",
            "-" * 72,
        ]
        for t in rows[:80]:
            lines.append(
                f"{t['timestamp']} | {t['pair']} {t['direction']} | "
                f"in {t['entry_price']} out {t['exit_price']} | "
                f"fees {t['fees_usd']} slip {t['slippage_pct']} | "
                f"PnL {t['pnl_usd']} | {t['exit_reason']}"
            )
            reason = str(t.get("ai_reasoning") or "").strip()
            if reason:
                lines.append(f"  AI Reason: {reason[:110]}")
        if len(rows) > 80:
            lines.append(f"... {len(rows) - 80} more trades omitted (export CSV for full ledger)")

        def _esc(s: str) -> str:
            return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

        content_ops: list[str] = ["BT", "/F1 9 Tf"]
        for i, line in enumerate(lines):
            yy = 800 - i * 11
            if yy < 40:
                break
            content_ops.append(f"1 0 0 1 36 {yy} Tm ({_esc(line[:110])}) Tj")
        content_ops.append("ET")
        stream = "\n".join(content_ops).encode("latin-1", errors="replace")

        objects: list[bytes] = []
        objects.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
        objects.append(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
        objects.append(
            b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
        )
        objects.append(
            f"4 0 obj<< /Length {len(stream)} >>stream\n".encode("ascii")
            + stream
            + b"\nendstream\nendobj\n"
        )
        objects.append(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>endobj\n")

        out = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for obj in objects:
            offsets.append(len(out))
            out.extend(obj)
        xref_pos = len(out)
        out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        out.extend(b"0000000000 65535 f \n")
        for off in offsets[1:]:
            out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
        out.extend(
            f"trailer<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
                "ascii"
            )
        )
        return bytes(out)


ledger_exporter = LedgerExporter()
