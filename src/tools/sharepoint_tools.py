"""Mock SharePoint integration tools.

In production these would use the Microsoft Graph API / SharePoint REST API
to retrieve contract documents from a SharePoint document library.
When ``SHAREPOINT_MOCK_MODE=true`` (default for PoC), pre-loaded sample data
is returned without any network calls.
"""

from __future__ import annotations

import logging
import sys
import os

from src.config import settings
from src.models.schemas import Contract

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

logger = logging.getLogger(__name__)


def _load_mock_contracts() -> list[Contract]:
    """Lazily import sample data to avoid circular imports."""
    from sample_data.mock_data import SAMPLE_CONTRACTS  # noqa: PLC0415

    return SAMPLE_CONTRACTS


# ---------------------------------------------------------------------------
# Public tool functions (called by the Contract Agent)
# ---------------------------------------------------------------------------


def list_contracts(
    contract_type: str | None = None,
    supplier_or_customer_id: str | None = None,
) -> list[dict]:
    """List available contracts from SharePoint (or mock store).

    Args:
        contract_type: Optional filter – one of ``supplier``, ``customer``,
            ``amendment``, ``framework``.
        supplier_or_customer_id: Optional filter by party identifier.

    Returns:
        List of contract summary dicts (without heavy clause payloads).
    """
    contracts = _load_mock_contracts()

    if contract_type:
        contracts = [c for c in contracts if c.contract_type.value == contract_type]
    if supplier_or_customer_id:
        contracts = [c for c in contracts if c.supplier_or_customer_id == supplier_or_customer_id]

    summaries = []
    for c in contracts:
        summaries.append(
            {
                "contract_id": c.contract_id,
                "contract_type": c.contract_type.value,
                "supplier_or_customer_id": c.supplier_or_customer_id,
                "supplier_or_customer_name": c.supplier_or_customer_name,
                "contract_name": c.contract_name,
                "effective_date": c.effective_date.isoformat(),
                "expiry_date": c.expiry_date.isoformat(),
                "currency": c.currency,
                "sharepoint_url": c.sharepoint_url,
            }
        )

    logger.info(
        "list_contracts returned %d results (mock_mode=%s)",
        len(summaries),
        settings.sharepoint_mock_mode,
    )
    return summaries


def get_contract_details(contract_id: str) -> dict | None:
    """Retrieve the full details of a single contract including clauses.

    Args:
        contract_id: The unique contract identifier.

    Returns:
        Full contract dict or ``None`` if not found.
    """
    contracts = _load_mock_contracts()
    for c in contracts:
        if c.contract_id == contract_id:
            logger.info("get_contract_details found contract %s (mock_mode=%s)", contract_id, settings.sharepoint_mock_mode)
            return c.model_dump(mode="json")

    logger.warning("get_contract_details: contract %s not found", contract_id)
    return None


def get_contracts_for_vendor(vendor_id: str) -> list[dict]:
    """Retrieve all contracts (including amendments) for a given vendor/customer.

    Args:
        vendor_id: The vendor or customer identifier.

    Returns:
        List of full contract dicts sorted by effective_date ascending.
    """
    contracts = _load_mock_contracts()
    matches = [c for c in contracts if c.supplier_or_customer_id == vendor_id]
    matches.sort(key=lambda c: c.effective_date)

    result = [c.model_dump(mode="json") for c in matches]
    logger.info(
        "get_contracts_for_vendor: vendor=%s returned %d contracts",
        vendor_id,
        len(result),
    )
    return result


def get_active_contract_on_date(vendor_id: str, invoice_date: str) -> dict | None:
    """Find the most specific active contract (latest amendment) for a vendor on a given date.

    Args:
        vendor_id: The vendor or customer identifier.
        invoice_date: ISO 8601 date string (``YYYY-MM-DD``).

    Returns:
        The most recently effective active contract/amendment dict, or ``None``.
    """
    from datetime import date  # noqa: PLC0415

    check_date = date.fromisoformat(invoice_date)
    contracts = _load_mock_contracts()

    relevant = [
        c
        for c in contracts
        if c.supplier_or_customer_id == vendor_id
        and c.effective_date <= check_date <= c.expiry_date
    ]

    if not relevant:
        logger.warning(
            "get_active_contract_on_date: no active contract for vendor=%s on %s",
            vendor_id,
            invoice_date,
        )
        return None

    # Prefer amendments (most recently effective)
    relevant.sort(key=lambda c: (c.effective_date, c.contract_type.value == "amendment"), reverse=True)
    active = relevant[0]
    logger.info(
        "get_active_contract_on_date: vendor=%s, date=%s → contract=%s",
        vendor_id,
        invoice_date,
        active.contract_id,
    )
    return active.model_dump(mode="json")
