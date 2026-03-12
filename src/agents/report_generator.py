"""Report Generator Agent.

Aggregates leakage findings and produces human-readable reports with
risk scores and remediation recommendations.
Registered as an Azure AI Agent with function tools for use in the
multi-agent orchestration.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.ai.agents.models import (
    FunctionTool,
    ToolSet,
)

from src.config import settings
from src.models.schemas import (
    AnalysisResult,
    InvoiceRiskScore,
    LeakageFinding,
    RiskLevel,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent identity
# ---------------------------------------------------------------------------

AGENT_NAME = "ReportGeneratorAgent"

AGENT_INSTRUCTIONS = """
You are the Report Generator Agent for the Contract Leakage Proof of Concept system.
Your responsibilities:
1. Aggregate individual leakage findings into structured invoice-level risk scores.
2. Generate an executive summary highlighting the most material risks.
3. Format a detailed findings report suitable for finance and procurement teams.
4. Rank invoices by risk score and total leakage amount.

Report format requirements:
- Executive summary: ≤ 3 paragraphs covering total exposure, top risks, and immediate actions.
- Invoice risk table: ranked by risk score descending.
- Detailed findings: each finding with category, risk level, evidence, and recommendation.
- Use Australian Dollar (AUD) as default currency.

Be clear, factual, and actionable. Avoid jargon. Cite contract clause text as evidence.
""".strip()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _aggregate_invoice_risk_scores(
    all_findings: list[dict],
    invoices: list[dict],
) -> list[InvoiceRiskScore]:
    """Group findings by invoice and compute per-invoice risk scores.

    Args:
        all_findings: Flat list of LeakageFinding dicts.
        invoices: List of invoice dicts.

    Returns:
        Sorted list of InvoiceRiskScore objects (highest risk first).
    """
    from src.tools.leakage_tools import calculate_risk_score  # noqa: PLC0415

    invoice_map = {inv["invoice_id"]: inv for inv in invoices}
    findings_by_invoice: dict[str, list[dict]] = {}
    for f in all_findings:
        inv_id = f.get("invoice_id", "UNKNOWN")
        findings_by_invoice.setdefault(inv_id, []).append(f)

    scores: list[InvoiceRiskScore] = []
    for inv_id, findings in findings_by_invoice.items():
        inv = invoice_map.get(inv_id, {})
        score_val = calculate_risk_score(findings)

        if score_val >= 40:
            overall_risk = RiskLevel.CRITICAL
        elif score_val >= 20:
            overall_risk = RiskLevel.HIGH
        elif score_val >= 10:
            overall_risk = RiskLevel.MEDIUM
        else:
            overall_risk = RiskLevel.LOW

        total_leakage = sum(
            abs(f.get("variance") or 0) for f in findings
        )
        finding_objs = [LeakageFinding(**f) for f in findings]

        scores.append(
            InvoiceRiskScore(
                invoice_id=inv_id,
                vendor_id=inv.get("vendor_id", "UNKNOWN"),
                vendor_name=inv.get("vendor_name", "Unknown Vendor"),
                contract_id=inv.get("contract_id"),
                overall_risk_level=overall_risk,
                risk_score=score_val,
                total_leakage_amount=total_leakage,
                currency=inv.get("currency", "AUD"),
                findings=finding_objs,
                summary=f"{len(findings)} finding(s) detected, estimated leakage "
                        f"{inv.get('currency', 'AUD')} {total_leakage:,.2f}.",
            )
        )

    scores.sort(key=lambda s: s.risk_score, reverse=True)
    return scores


# ---------------------------------------------------------------------------
# Function definitions for Azure AI Agent tool registration
# ---------------------------------------------------------------------------


def _build_analysis_result_tool(
    all_findings_json: str,
    invoices_json: str,
    contracts_analysed: str = "0",
) -> str:
    """Aggregate findings into a structured AnalysisResult.

    Args:
        all_findings_json: JSON string of a flat list of all LeakageFinding dicts.
        invoices_json: JSON string of the list of analysed Invoice dicts.
        contracts_analysed: Number of contracts analysed (as a string).

    Returns:
        JSON string with the full AnalysisResult.
    """
    all_findings = json.loads(all_findings_json)
    invoices = json.loads(invoices_json)

    risk_scores = _aggregate_invoice_risk_scores(all_findings, invoices)

    total_leakage = sum(s.total_leakage_amount for s in risk_scores)
    high_risk = sum(1 for s in risk_scores if s.overall_risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL))
    critical_risk = sum(1 for s in risk_scores if s.overall_risk_level == RiskLevel.CRITICAL)

    result = AnalysisResult(
        analysis_id=f"ANLYS-{uuid.uuid4().hex[:8].upper()}",
        run_at=datetime.utcnow(),
        contracts_analysed=int(contracts_analysed),
        invoices_analysed=len(invoices),
        total_leakage_amount=total_leakage,
        currency="AUD",
        invoice_risk_scores=risk_scores,
        high_risk_count=high_risk,
        critical_risk_count=critical_risk,
        detailed_findings=[LeakageFinding(**f) for f in all_findings],
    )

    return json.dumps(result.model_dump(mode="json"), default=str)


def _generate_executive_summary_tool(analysis_result_json: str) -> str:
    """Generate an executive summary from an AnalysisResult.

    Args:
        analysis_result_json: JSON string of the AnalysisResult.

    Returns:
        Plain-text executive summary string (JSON-encoded).
    """
    result = json.loads(analysis_result_json)
    total_leakage = result.get("total_leakage_amount", 0)
    currency = result.get("currency", "AUD")
    critical = result.get("critical_risk_count", 0)
    high = result.get("high_risk_count", 0)
    inv_count = result.get("invoices_analysed", 0)
    ctr_count = result.get("contracts_analysed", 0)
    run_at = result.get("run_at", "")

    # Top findings by risk
    top_findings = sorted(
        result.get("detailed_findings", []),
        key=lambda f: {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(f.get("risk_level", "low"), 0),
        reverse=True,
    )[:3]

    top_text = "\n".join(
        f"  • [{f.get('risk_level','').upper()}] {f.get('description','')}"
        for f in top_findings
    )

    summary = (
        f"CONTRACT LEAKAGE ANALYSIS – EXECUTIVE SUMMARY\n"
        f"Prepared: {run_at}\n\n"
        f"Analysis covered {inv_count} invoice(s) across {ctr_count} contract(s). "
        f"Total estimated leakage identified: {currency} {total_leakage:,.2f}. "
        f"{critical} invoice(s) are rated CRITICAL risk and {high} are rated HIGH risk, "
        f"requiring immediate attention.\n\n"
        f"Top findings:\n{top_text}\n\n"
        f"Recommended immediate actions:\n"
        f"  1. Escalate all CRITICAL findings to Procurement and Finance leadership.\n"
        f"  2. Issue credit/debit note requests for pricing discrepancies.\n"
        f"  3. Confirm contract renewal status for expired agreements.\n"
        f"  4. Initiate annual rebate reconciliation with relevant suppliers."
    )

    return json.dumps({"executive_summary": summary})


def _format_findings_table_tool(analysis_result_json: str) -> str:
    """Format a markdown table of invoice risk scores for reporting.

    Args:
        analysis_result_json: JSON string of the AnalysisResult.

    Returns:
        JSON string with a 'markdown_table' key containing the formatted table.
    """
    result = json.loads(analysis_result_json)
    scores = result.get("invoice_risk_scores", [])

    header = "| Invoice ID | Vendor | Contract | Risk Level | Risk Score | Leakage (AUD) | # Findings |"
    divider = "|------------|--------|----------|------------|------------|---------------|------------|"
    rows = []
    for s in scores:
        rows.append(
            f"| {s['invoice_id']} | {s['vendor_name']} | {s.get('contract_id','N/A')} "
            f"| {s['overall_risk_level'].upper()} | {s['risk_score']:.0f}/100 "
            f"| {s['total_leakage_amount']:,.2f} | {len(s.get('findings',[]))} |"
        )

    table = "\n".join([header, divider] + rows)
    return json.dumps({"markdown_table": table})


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

AGENT_TOOLS = [
    _build_analysis_result_tool,
    _generate_executive_summary_tool,
    _format_findings_table_tool,
]


def create_report_generator_agent(project_client: AIProjectClient) -> Any:
    """Create (or retrieve) the Report Generator Agent in Azure AI Foundry.

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
    logger.info("ReportGeneratorAgent created: id=%s", agent.id)
    return agent
