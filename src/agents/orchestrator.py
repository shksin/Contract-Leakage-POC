"""Orchestrator Agent.

The top-level agent that coordinates the Contract, Invoice, Leakage Detector,
and Report Generator agents using the Azure AI Foundry Connected Agents pattern.

Architecture
────────────
User / API
    │
    ▼
OrchestratorAgent (this file)
    ├─ ContractAgent      → SharePoint tools
    ├─ InvoiceAgent       → BigQuery tools
    ├─ LeakageDetectorAgent → analysis tools
    └─ ReportGeneratorAgent → report formatting tools
"""

from __future__ import annotations

import logging
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.ai.agents.models import (
    ConnectedAgentTool,
    ToolSet,
)

from src.agents.contract_agent import create_contract_agent
from src.agents.invoice_agent import create_invoice_agent
from src.agents.leakage_detector import create_leakage_detector_agent
from src.agents.report_generator import create_report_generator_agent
from src.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Orchestrator identity
# ---------------------------------------------------------------------------

ORCHESTRATOR_NAME = "ContractLeakageOrchestrator"

ORCHESTRATOR_INSTRUCTIONS = """
You are the Contract Leakage Orchestrator for Orica's Contract Leakage Proof of Concept.

Your job is to coordinate a team of specialised agents to identify financial leakage
between supplier/customer contracts and actual invoicing behaviour.

## Workflow

For each leakage analysis request, follow these steps:

### Step 1 – Retrieve invoices (via InvoiceAgent)
- Fetch the relevant invoices from BigQuery using the provided filters (vendor, date range, etc.).
- If no filters are given, retrieve all available invoices.

### Step 2 – Retrieve contracts (via ContractAgent)
- For each invoice, find the active contract (including latest amendment) on the invoice date.
- If no active contract is found, record this as an expired/missing contract risk.

### Step 3 – Detect leakage (via LeakageDetectorAgent)
For each invoice/contract pair, check ALL of the following:
  a) Pricing drift – are unit prices correct per the contracted tier?
  b) Volume tier compliance – was the correct pricing tier applied for the order quantity?
  c) Missed rebates – has the annual/quarterly rebate threshold been reached without a credit note?
  d) Early payment discounts – was the invoice paid within the discount window without applying the discount?
  e) Expired contract terms – is the invoice dated after the contract expiry?

Collect ALL findings across all invoices.

### Step 4 – Generate report (via ReportGeneratorAgent)
- Aggregate all findings into an AnalysisResult.
- Generate an executive summary.
- Format a risk table ranked by risk score.
- Return the complete report including the executive summary and detailed findings.

## Output format
Always return:
1. An executive summary (plain text).
2. A risk ranking table (Markdown).
3. A detailed findings list with evidence and recommendations.
4. The total estimated leakage amount.

## Important rules
- Never fabricate invoice or contract data – always use the agent tools.
- Always check for the latest amendment when looking up contract terms.
- Be conservative – flag potential leakage even if variance is small.
- Clearly state currency in all monetary figures.
""".strip()


# ---------------------------------------------------------------------------
# Orchestrator factory
# ---------------------------------------------------------------------------


def create_orchestrator(project_client: AIProjectClient) -> Any:
    """Create all specialist agents and the orchestrator in Azure AI Foundry.

    This function:
    1. Creates the four specialist agents.
    2. Creates the orchestrator with ``ConnectedAgentTool`` references to each.

    Args:
        project_client: An authenticated ``AIProjectClient`` instance.

    Returns:
        The orchestrator ``Agent`` object.
    """
    logger.info("Creating specialist agents...")

    contract_agent = create_contract_agent(project_client)
    invoice_agent = create_invoice_agent(project_client)
    leakage_agent = create_leakage_detector_agent(project_client)
    report_agent = create_report_generator_agent(project_client)

    logger.info("Creating orchestrator with connected agent tools...")

    toolset = ToolSet()
    toolset.add(
        ConnectedAgentTool(
            id=contract_agent.id,
            name="ContractAgent",
            description=(
                "Retrieves and enriches contract data from SharePoint. "
                "Use to look up contract details, pricing tiers, rebate structures, "
                "expiry dates, and to find the active contract for a vendor on a specific date."
            ),
        )
    )
    toolset.add(
        ConnectedAgentTool(
            id=invoice_agent.id,
            name="InvoiceAgent",
            description=(
                "Retrieves invoice records from BigQuery (GCP). "
                "Use to fetch invoices by vendor, contract, or date range, "
                "and to obtain vendor annual spend for rebate checks."
            ),
        )
    )
    toolset.add(
        ConnectedAgentTool(
            id=leakage_agent.id,
            name="LeakageDetectorAgent",
            description=(
                "Analyses invoice/contract pairs for financial leakage. "
                "Detects pricing drift, missed rebates, early payment discount omissions, "
                "volume tier violations, and expired contract terms. "
                "Returns structured findings with risk levels and evidence."
            ),
        )
    )
    toolset.add(
        ConnectedAgentTool(
            id=report_agent.id,
            name="ReportGeneratorAgent",
            description=(
                "Aggregates leakage findings into structured risk reports. "
                "Generates executive summaries, risk ranking tables, and detailed findings. "
                "Use after all leakage detection is complete."
            ),
        )
    )

    orchestrator = project_client.agents.create_agent(
        model=settings.azure_ai_model_deployment,
        name=ORCHESTRATOR_NAME,
        instructions=ORCHESTRATOR_INSTRUCTIONS,
        toolset=toolset,
    )

    logger.info("Orchestrator created: id=%s", orchestrator.id)
    return orchestrator


def run_analysis(
    project_client: AIProjectClient,
    orchestrator: Any,
    vendor_ids: list[str] | None = None,
    contract_ids: list[str] | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
    leakage_categories: list[str] | None = None,
) -> str:
    """Run a leakage analysis via the orchestrator agent.

    Args:
        project_client: An authenticated ``AIProjectClient`` instance.
        orchestrator: The orchestrator ``Agent`` object.
        vendor_ids: Optional list of vendor IDs to restrict analysis.
        contract_ids: Optional list of contract IDs to restrict analysis.
        period_start: Optional ISO date string for invoice date range start.
        period_end: Optional ISO date string for invoice date range end.
        leakage_categories: Optional list of leakage category strings to check.

    Returns:
        The orchestrator's final text response (executive summary + report).
    """
    # Build the user prompt
    filters = []
    if vendor_ids:
        filters.append(f"vendors: {', '.join(vendor_ids)}")
    if contract_ids:
        filters.append(f"contracts: {', '.join(contract_ids)}")
    if period_start or period_end:
        date_range = f"{period_start or 'all time'} to {period_end or 'present'}"
        filters.append(f"date range: {date_range}")
    if leakage_categories:
        filters.append(f"leakage categories: {', '.join(leakage_categories)}")

    filter_text = (
        "Filters applied: " + "; ".join(filters) + "."
        if filters
        else "No filters – analyse all available invoices and contracts."
    )

    user_message = (
        "Please perform a complete contract leakage analysis. "
        f"{filter_text} "
        "Follow the full workflow: retrieve invoices, match contracts, detect all leakage types, "
        "and return a complete report with executive summary, risk table, and detailed findings."
    )

    logger.info("Starting analysis run. User message: %s", user_message)

    from azure.ai.agents.models import AgentThreadCreationOptions, ThreadMessageOptions  # noqa: PLC0415

    thread_options = AgentThreadCreationOptions(
        messages=[
            ThreadMessageOptions(role="user", content=user_message)
        ]
    )

    run = project_client.agents.create_thread_and_process_run(
        agent_id=orchestrator.id,
        thread=thread_options,
    )

    logger.info("Run completed: status=%s, id=%s", run.status, run.id)

    messages = project_client.agents.messages.list(thread_id=run.thread_id)
    for msg in messages:
        if msg.role == "assistant":
            for content_block in msg.content:
                if hasattr(content_block, "text"):
                    return content_block.text.value

    return "No response generated by the orchestrator."
