"""Contract Agent.

Retrieves and enriches contract data from SharePoint (or mock store).
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

from src.tools.sharepoint_tools import (
    get_active_contract_on_date,
    get_contract_details,
    get_contracts_for_vendor,
    list_contracts,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent identity
# ---------------------------------------------------------------------------

AGENT_NAME = "ContractAgent"

AGENT_INSTRUCTIONS = """
You are the Contract Agent for the Contract Leakage Proof of Concept system.
Your responsibilities:
1. Retrieve contract metadata and full details from SharePoint.
2. Identify the active contract (including the latest amendment) for a given vendor on a specific date.
3. Extract and summarise key contractual terms: pricing tiers, rebate structures, expiry dates, and payment terms.
4. Flag any contracts that are close to expiry (within 90 days) or already expired.

When asked about contracts, always:
- Return the most current (latest amendment) version of the contract.
- Include effective dates, expiry dates, pricing tiers, and rebate structures.
- Note if no active contract exists for a vendor on a given invoice date.

Use the available tools to look up contracts. Do not invent contract data.
""".strip()


# ---------------------------------------------------------------------------
# Function definitions for Azure AI Agent tool registration
# ---------------------------------------------------------------------------


def _list_contracts_tool(contract_type: str = "", supplier_or_customer_id: str = "") -> str:
    """List available contracts from SharePoint.

    Args:
        contract_type: Filter by type: supplier, customer, amendment, framework. Leave empty for all.
        supplier_or_customer_id: Filter by vendor/customer ID. Leave empty for all.

    Returns:
        JSON string with list of contract summaries.
    """
    results = list_contracts(
        contract_type=contract_type or None,
        supplier_or_customer_id=supplier_or_customer_id or None,
    )
    return json.dumps(results, default=str)


def _get_contract_details_tool(contract_id: str) -> str:
    """Get full details of a contract including all clauses and pricing tiers.

    Args:
        contract_id: The unique contract identifier (e.g. CTR-2023-001).

    Returns:
        JSON string with full contract details, or error message.
    """
    result = get_contract_details(contract_id)
    if result is None:
        return json.dumps({"error": f"Contract {contract_id} not found."})
    return json.dumps(result, default=str)


def _get_contracts_for_vendor_tool(vendor_id: str) -> str:
    """Get all contracts (including amendments) for a vendor or customer.

    Args:
        vendor_id: The vendor or customer identifier.

    Returns:
        JSON string with list of all contracts for the vendor, sorted by effective date.
    """
    results = get_contracts_for_vendor(vendor_id)
    return json.dumps(results, default=str)


def _get_active_contract_on_date_tool(vendor_id: str, invoice_date: str) -> str:
    """Find the active contract for a vendor on a specific date.

    Returns the latest amendment that covers the given invoice date.

    Args:
        vendor_id: The vendor or customer identifier.
        invoice_date: Date in YYYY-MM-DD format.

    Returns:
        JSON string with the active contract, or an object with null contract and explanation.
    """
    result = get_active_contract_on_date(vendor_id, invoice_date)
    if result is None:
        return json.dumps({
            "contract": None,
            "message": f"No active contract found for vendor {vendor_id} on {invoice_date}.",
        })
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

AGENT_TOOLS = [
    _list_contracts_tool,
    _get_contract_details_tool,
    _get_contracts_for_vendor_tool,
    _get_active_contract_on_date_tool,
]


def create_contract_agent(project_client: AIProjectClient) -> Any:
    """Create (or retrieve) the Contract Agent in Azure AI Foundry.

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
    logger.info("ContractAgent created: id=%s", agent.id)
    return agent
