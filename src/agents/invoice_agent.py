"""Invoice Agent.

Retrieves and analyses invoice data from BigQuery (or mock store).
Registered as an Azure AI Agent with function tools for use in the
multi-agent orchestration.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.ai.agents.models import (
    FunctionTool,
    ToolSet,
)

from src.config import settings
from src.tools.bigquery_tools import (
    get_invoice_by_id,
    get_invoice_schema,
    get_invoices,
    get_vendor_annual_spend,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent identity
# ---------------------------------------------------------------------------

AGENT_NAME = "InvoiceAgent"

AGENT_INSTRUCTIONS = """
You are the Invoice Agent for the Contract Leakage Proof of Concept system.
Your responsibilities:
1. Retrieve invoice records from BigQuery (GCP), including header and line-item detail.
2. Return the BigQuery schema when asked, to help understand the data structure.
3. Aggregate spend data for vendor-level rebate threshold checks.
4. Provide filtered invoice lists by vendor, contract, or date range.

When returning invoices, always include:
- invoice_id, vendor_id, vendor_name, contract_id, invoice_date
- Monetary fields: subtotal, tax_amount, discount_applied, total_amount, currency
- All line items with unit_price, quantity, and line_total

Use the available tools to retrieve data. Do not fabricate invoice records.
""".strip()


# ---------------------------------------------------------------------------
# Function definitions for Azure AI Agent tool registration
# ---------------------------------------------------------------------------


def _get_invoice_schema_tool() -> str:
    """Return the BigQuery invoice schema (tables, fields, data types, key identifiers).

    Returns:
        JSON string describing the invoice dataset schema.
    """
    return json.dumps(get_invoice_schema(), default=str)


def _get_invoices_tool(
    vendor_id: str = "",
    contract_id: str = "",
    period_start: str = "",
    period_end: str = "",
) -> str:
    """Retrieve invoices with optional filters.

    Args:
        vendor_id: Filter by vendor ID. Leave empty for all vendors.
        contract_id: Filter by contract ID. Leave empty for all contracts.
        period_start: Start date filter (YYYY-MM-DD). Leave empty for no start limit.
        period_end: End date filter (YYYY-MM-DD). Leave empty for no end limit.

    Returns:
        JSON string with list of invoices including line items.
    """
    results = get_invoices(
        vendor_id=vendor_id or None,
        contract_id=contract_id or None,
        period_start=period_start or None,
        period_end=period_end or None,
    )
    return json.dumps(results, default=str)


def _get_invoice_by_id_tool(invoice_id: str) -> str:
    """Retrieve a single invoice by its primary key.

    Args:
        invoice_id: The unique invoice identifier.

    Returns:
        JSON string with the invoice details, or an error object.
    """
    result = get_invoice_by_id(invoice_id)
    if result is None:
        return json.dumps({"error": f"Invoice {invoice_id} not found."})
    return json.dumps(result, default=str)


def _get_vendor_annual_spend_tool(vendor_id: str, year: str) -> str:
    """Aggregate total spend with a vendor for a calendar year.

    Useful for rebate threshold checks.

    Args:
        vendor_id: The vendor identifier.
        year: Calendar year as a string (e.g. '2024').

    Returns:
        JSON string with vendor_id, year, total_spend, currency, and invoice_count.
    """
    result = get_vendor_annual_spend(vendor_id, int(year))
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

AGENT_TOOLS = [
    _get_invoice_schema_tool,
    _get_invoices_tool,
    _get_invoice_by_id_tool,
    _get_vendor_annual_spend_tool,
]


def create_invoice_agent(project_client: AIProjectClient) -> Any:
    """Create (or retrieve) the Invoice Agent in Azure AI Foundry.

    Args:
        project_client: An authenticated ``AIProjectClient`` instance.

    Returns:
        The created ``Agent`` object.
    """
    toolset = ToolSet()
    toolset.add(FunctionTool(functions=set(AGENT_TOOLS)))

    agent = project_client.agents.create_agent(
        model=settings.azure_ai_model_deployment,
        name=AGENT_NAME,
        instructions=AGENT_INSTRUCTIONS,
        toolset=toolset,
    )
    logger.info("InvoiceAgent created: id=%s", agent.id)
    return agent
