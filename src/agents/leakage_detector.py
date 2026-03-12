"""Leakage Detector Agent.

Compares invoice data against contract terms to identify financial leakage.
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
from src.tools.leakage_tools import (
    calculate_risk_score,
    check_contract_expiry,
    check_early_payment_discount,
    check_rebate_compliance,
    detect_pricing_drift,
    validate_volume_tiers,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent identity
# ---------------------------------------------------------------------------

AGENT_NAME = "LeakageDetectorAgent"

AGENT_INSTRUCTIONS = """
You are the Leakage Detector Agent for the Contract Leakage Proof of Concept system.
Your responsibilities:
1. Detect pricing drift: identify where invoice unit prices deviate from contracted rates.
2. Detect missed rebates: identify where volume/spend thresholds have been met but rebates not applied.
3. Detect early payment discount omissions: identify invoices paid within the discount window without the discount.
4. Detect expired contract terms applied: flag invoices referencing contracts that had expired at invoice date.
5. Detect volume tier breaches: flag where the wrong pricing tier was applied based on order quantity.
6. Calculate a risk score (0–100) for each invoice based on findings.

For each analysis, return:
- A list of findings with finding_id, category, risk_level, description, expected_value, actual_value, variance, evidence, and recommendation.
- A risk score summarising the overall exposure.

Be precise. Show your reasoning using the contract clause text as evidence.
""".strip()


# ---------------------------------------------------------------------------
# Function definitions for Azure AI Agent tool registration
# ---------------------------------------------------------------------------


def _detect_pricing_drift_tool(invoice_json: str, contract_json: str) -> str:
    """Detect unit-price discrepancies between an invoice and its contract.

    Args:
        invoice_json: JSON string of the invoice dict.
        contract_json: JSON string of the active contract dict.

    Returns:
        JSON string with list of LeakageFinding dicts.
    """
    invoice = json.loads(invoice_json)
    contract = json.loads(contract_json)
    findings = detect_pricing_drift(invoice, contract)
    return json.dumps(findings, default=str)


def _check_rebate_compliance_tool(
    vendor_id: str,
    year: str,
    annual_spend: str,
    contract_json: str,
    currency: str = "AUD",
) -> str:
    """Check whether annual volume rebates have been claimed for a vendor.

    Args:
        vendor_id: The vendor identifier.
        year: Calendar year as a string (e.g. '2024').
        annual_spend: Total annual spend as a string (e.g. '5200000.00').
        contract_json: JSON string of the contract dict.
        currency: Currency code (default AUD).

    Returns:
        JSON string with list of LeakageFinding dicts.
    """
    contract = json.loads(contract_json)
    findings = check_rebate_compliance(
        vendor_id=vendor_id,
        year=int(year),
        annual_spend=float(annual_spend),
        contract=contract,
        currency=currency,
    )
    return json.dumps(findings, default=str)


def _check_early_payment_discount_tool(invoice_json: str, contract_json: str) -> str:
    """Check for unclaimed early payment discounts on an invoice.

    Args:
        invoice_json: JSON string of the invoice dict.
        contract_json: JSON string of the active contract dict.

    Returns:
        JSON string with list of LeakageFinding dicts.
    """
    invoice = json.loads(invoice_json)
    contract = json.loads(contract_json)
    findings = check_early_payment_discount(invoice, contract)
    return json.dumps(findings, default=str)


def _validate_volume_tiers_tool(invoice_json: str, contract_json: str) -> str:
    """Validate that the correct pricing tier was applied for the order volume.

    Args:
        invoice_json: JSON string of the invoice dict.
        contract_json: JSON string of the active contract dict.

    Returns:
        JSON string with list of LeakageFinding dicts.
    """
    invoice = json.loads(invoice_json)
    contract = json.loads(contract_json)
    findings = validate_volume_tiers(invoice, contract)
    return json.dumps(findings, default=str)


def _check_contract_expiry_tool(invoice_json: str, contract_json: str) -> str:
    """Flag if an invoice is dated after the contract expiry date.

    Args:
        invoice_json: JSON string of the invoice dict.
        contract_json: JSON string of the contract dict.

    Returns:
        JSON string with list of LeakageFinding dicts.
    """
    invoice = json.loads(invoice_json)
    contract = json.loads(contract_json)
    findings = check_contract_expiry(invoice, contract)
    return json.dumps(findings, default=str)


def _calculate_risk_score_tool(findings_json: str) -> str:
    """Calculate an aggregate risk score (0–100) from a list of findings.

    Args:
        findings_json: JSON string with list of LeakageFinding dicts.

    Returns:
        JSON string with keys 'risk_score' (float) and 'interpretation' (string).
    """
    findings = json.loads(findings_json)
    score = calculate_risk_score(findings)
    if score >= 40:
        interpretation = "CRITICAL – Immediate escalation required."
    elif score >= 20:
        interpretation = "HIGH – Management review required within 5 business days."
    elif score >= 10:
        interpretation = "MEDIUM – Review and resolve within 30 days."
    else:
        interpretation = "LOW – Monitor and review at next scheduled audit."
    return json.dumps({"risk_score": score, "interpretation": interpretation})


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

AGENT_TOOLS = [
    _detect_pricing_drift_tool,
    _check_rebate_compliance_tool,
    _check_early_payment_discount_tool,
    _validate_volume_tiers_tool,
    _check_contract_expiry_tool,
    _calculate_risk_score_tool,
]


def create_leakage_detector_agent(project_client: AIProjectClient) -> Any:
    """Create (or retrieve) the Leakage Detector Agent in Azure AI Foundry.

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
    logger.info("LeakageDetectorAgent created: id=%s", agent.id)
    return agent
