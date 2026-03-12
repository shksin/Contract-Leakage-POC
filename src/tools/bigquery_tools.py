"""Mock BigQuery / GCP integration tools.

In production these would execute parameterised SQL queries against
BigQuery using the ``google-cloud-bigquery`` client library.
When ``BIGQUERY_MOCK_MODE=true`` (default for PoC), pre-loaded sample data
is returned without any GCP calls.

Physical schema (``finance_data`` dataset on GCP):
──────────────────────────────────────────────────
Table: invoices
  invoice_id          STRING      NOT NULL  -- PK
  purchase_order_id   STRING               -- FK → purchase_orders
  vendor_id           STRING      NOT NULL  -- FK → vendors
  vendor_name         STRING      NOT NULL
  contract_id         STRING               -- FK → contracts (nullable)
  subtotal            NUMERIC     NOT NULL
  tax_amount          NUMERIC     NOT NULL
  discount_applied    NUMERIC     NOT NULL
  total_amount        NUMERIC     NOT NULL
  currency            STRING      NOT NULL  -- ISO 4217
  invoice_date        DATE        NOT NULL
  service_period_start DATE
  service_period_end   DATE
  due_date            DATE
  payment_date        DATE
  created_at          TIMESTAMP   NOT NULL

Table: invoice_line_items
  line_item_id        STRING      NOT NULL  -- PK
  invoice_id          STRING      NOT NULL  -- FK → invoices
  material_code       STRING      NOT NULL
  description         STRING      NOT NULL
  quantity            NUMERIC     NOT NULL
  unit_of_measure     STRING      NOT NULL
  unit_price          NUMERIC     NOT NULL
  line_total          NUMERIC     NOT NULL
  currency            STRING      NOT NULL
"""

from __future__ import annotations

import logging
from datetime import date

from src.config import settings
from src.models.schemas import Invoice

logger = logging.getLogger(__name__)


def _load_mock_invoices() -> list[Invoice]:
    """Lazily import sample data to avoid circular imports."""
    from sample_data.mock_data import SAMPLE_INVOICES  # noqa: PLC0415

    return SAMPLE_INVOICES


# ---------------------------------------------------------------------------
# Public tool functions (called by the Invoice Agent)
# ---------------------------------------------------------------------------


def get_invoice_schema() -> dict:
    """Return the logical schema of the BigQuery invoice tables.

    Returns:
        Dict describing the two invoice-related tables and their fields.
    """
    return {
        "dataset": "finance_data",
        "tables": {
            "invoices": {
                "description": "Header-level invoice records",
                "key_identifiers": ["invoice_id", "vendor_id", "contract_id", "purchase_order_id"],
                "monetary_fields": ["subtotal", "tax_amount", "discount_applied", "total_amount"],
                "timestamps": ["invoice_date", "service_period_start", "service_period_end", "due_date", "payment_date", "created_at"],
                "fields": {
                    "invoice_id": {"type": "STRING", "mode": "REQUIRED", "description": "Primary key"},
                    "purchase_order_id": {"type": "STRING", "mode": "NULLABLE"},
                    "vendor_id": {"type": "STRING", "mode": "REQUIRED"},
                    "vendor_name": {"type": "STRING", "mode": "REQUIRED"},
                    "contract_id": {"type": "STRING", "mode": "NULLABLE"},
                    "subtotal": {"type": "NUMERIC", "mode": "REQUIRED"},
                    "tax_amount": {"type": "NUMERIC", "mode": "REQUIRED"},
                    "discount_applied": {"type": "NUMERIC", "mode": "REQUIRED"},
                    "total_amount": {"type": "NUMERIC", "mode": "REQUIRED"},
                    "currency": {"type": "STRING", "mode": "REQUIRED"},
                    "invoice_date": {"type": "DATE", "mode": "REQUIRED"},
                    "service_period_start": {"type": "DATE", "mode": "NULLABLE"},
                    "service_period_end": {"type": "DATE", "mode": "NULLABLE"},
                    "due_date": {"type": "DATE", "mode": "NULLABLE"},
                    "payment_date": {"type": "DATE", "mode": "NULLABLE"},
                    "created_at": {"type": "TIMESTAMP", "mode": "REQUIRED"},
                },
            },
            "invoice_line_items": {
                "description": "Line-item detail for each invoice",
                "key_identifiers": ["line_item_id", "invoice_id", "material_code"],
                "monetary_fields": ["unit_price", "line_total"],
                "timestamps": [],
                "fields": {
                    "line_item_id": {"type": "STRING", "mode": "REQUIRED", "description": "Primary key"},
                    "invoice_id": {"type": "STRING", "mode": "REQUIRED", "description": "FK → invoices"},
                    "material_code": {"type": "STRING", "mode": "REQUIRED"},
                    "description": {"type": "STRING", "mode": "REQUIRED"},
                    "quantity": {"type": "NUMERIC", "mode": "REQUIRED"},
                    "unit_of_measure": {"type": "STRING", "mode": "REQUIRED"},
                    "unit_price": {"type": "NUMERIC", "mode": "REQUIRED"},
                    "line_total": {"type": "NUMERIC", "mode": "REQUIRED"},
                    "currency": {"type": "STRING", "mode": "REQUIRED"},
                },
            },
        },
    }


def get_invoices(
    vendor_id: str | None = None,
    contract_id: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
) -> list[dict]:
    """Retrieve invoices matching the given filters.

    Args:
        vendor_id: Optional vendor/supplier identifier filter.
        contract_id: Optional contract identifier filter.
        period_start: Optional ISO 8601 start date for ``invoice_date`` filter.
        period_end: Optional ISO 8601 end date for ``invoice_date`` filter.

    Returns:
        List of invoice dicts including nested line items.
    """
    invoices = _load_mock_invoices()

    if vendor_id:
        invoices = [i for i in invoices if i.vendor_id == vendor_id]
    if contract_id:
        invoices = [i for i in invoices if i.contract_id == contract_id]
    if period_start:
        start = date.fromisoformat(period_start)
        invoices = [i for i in invoices if i.invoice_date >= start]
    if period_end:
        end = date.fromisoformat(period_end)
        invoices = [i for i in invoices if i.invoice_date <= end]

    result = [i.model_dump(mode="json") for i in invoices]
    logger.info(
        "get_invoices returned %d results (vendor=%s, contract=%s, mock_mode=%s)",
        len(result),
        vendor_id,
        contract_id,
        settings.bigquery_mock_mode,
    )
    return result


def get_invoice_by_id(invoice_id: str) -> dict | None:
    """Retrieve a single invoice by its primary key.

    Args:
        invoice_id: The unique invoice identifier.

    Returns:
        Invoice dict with line items, or ``None`` if not found.
    """
    invoices = _load_mock_invoices()
    for inv in invoices:
        if inv.invoice_id == invoice_id:
            logger.info("get_invoice_by_id found %s (mock_mode=%s)", invoice_id, settings.bigquery_mock_mode)
            return inv.model_dump(mode="json")

    logger.warning("get_invoice_by_id: invoice %s not found", invoice_id)
    return None


def get_vendor_annual_spend(vendor_id: str, year: int) -> dict:
    """Aggregate total spend with a vendor for a calendar year.

    Useful for rebate threshold checks.

    Args:
        vendor_id: The vendor identifier.
        year: Calendar year (e.g. 2024).

    Returns:
        Dict with ``vendor_id``, ``year``, ``total_spend``, ``currency``,
        and ``invoice_count``.
    """
    invoices = _load_mock_invoices()
    relevant = [
        i
        for i in invoices
        if i.vendor_id == vendor_id and i.invoice_date.year == year
    ]
    total = sum(i.subtotal for i in relevant)
    currency = relevant[0].currency if relevant else "AUD"

    return {
        "vendor_id": vendor_id,
        "year": year,
        "total_spend": total,
        "currency": currency,
        "invoice_count": len(relevant),
    }
