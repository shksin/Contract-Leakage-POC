"""FastAPI application entry point for the Contract Leakage POC.

Exposes REST endpoints to:
  - Trigger contract leakage analysis via the multi-agent orchestrator
  - Run local analysis (without Azure AI Foundry) using the tool layer directly
  - Health check
  - Return the BigQuery invoice schema

Run locally:
    uvicorn src.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from src.config import settings
from src.models.schemas import (
    AnalysisRequest,
    AnalysisResult,
    HealthResponse,
    InvoiceRiskScore,
    LeakageFinding,
    RiskLevel,
)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Local (non-AI) analysis – uses tool functions directly
# ---------------------------------------------------------------------------


def _run_local_analysis(request: AnalysisRequest) -> AnalysisResult:
    """Execute leakage analysis using the tool layer without Azure AI Foundry.

    This is the default path when ``AZURE_AI_PROJECT_CONNECTION_STRING`` is
    not configured, which is the case in the PoC / demo environment.
    """
    from src.tools.bigquery_tools import get_invoices, get_vendor_annual_spend
    from src.tools.leakage_tools import (
        calculate_risk_score,
        check_contract_expiry,
        check_early_payment_discount,
        check_rebate_compliance,
        detect_pricing_drift,
    )
    from src.tools.sharepoint_tools import get_active_contract_on_date

    # 1. Retrieve invoices
    invoices = get_invoices(
        vendor_id=request.vendor_ids[0] if request.vendor_ids and len(request.vendor_ids) == 1 else None,
        contract_id=request.contract_ids[0] if request.contract_ids and len(request.contract_ids) == 1 else None,
        period_start=request.period_start.isoformat() if request.period_start else None,
        period_end=request.period_end.isoformat() if request.period_end else None,
    )

    # Apply multi-vendor / multi-contract filters that weren't handled above
    if request.vendor_ids and len(request.vendor_ids) > 1:
        invoices = [i for i in invoices if i["vendor_id"] in request.vendor_ids]
    if request.contract_ids and len(request.contract_ids) > 1:
        invoices = [i for i in invoices if i.get("contract_id") in request.contract_ids]

    all_findings: list[dict] = []
    contracts_seen: set[str] = set()

    # 2. For each invoice, find its active contract and run all checks
    for inv in invoices:
        vendor_id = inv["vendor_id"]
        invoice_date = str(inv["invoice_date"])
        contract = get_active_contract_on_date(vendor_id, invoice_date)

        # Track the referenced contract as well for accurate contract count
        if inv.get("contract_id"):
            contracts_seen.add(inv["contract_id"])

        if contract:
            contracts_seen.add(contract["contract_id"])

            # Pricing drift / volume tier
            findings = detect_pricing_drift(inv, contract)
            all_findings.extend(findings)

            # Contract expiry
            findings = check_contract_expiry(inv, contract)
            all_findings.extend(findings)

            # Early payment discount
            findings = check_early_payment_discount(inv, contract)
            all_findings.extend(findings)
        else:
            # No active contract – flag as expired terms applied
            if inv.get("contract_id"):
                from src.tools.sharepoint_tools import get_contract_details
                past_contract = get_contract_details(inv["contract_id"])
                if past_contract:
                    contracts_seen.add(past_contract["contract_id"])
                    findings = check_contract_expiry(inv, past_contract)
                    all_findings.extend(findings)

    # 3. Annual rebate checks per vendor
    vendor_years: set[tuple[str, int]] = set()
    for inv in invoices:
        if inv.get("invoice_date"):
            inv_date = date.fromisoformat(str(inv["invoice_date"]))
            vendor_years.add((inv["vendor_id"], inv_date.year))

    for vendor_id, year in vendor_years:
        from src.tools.sharepoint_tools import get_contracts_for_vendor
        vendor_contracts = get_contracts_for_vendor(vendor_id)
        spend_data = get_vendor_annual_spend(vendor_id, year)
        for ctr in vendor_contracts:
            if not ctr.get("rebates"):
                continue
            findings = check_rebate_compliance(
                vendor_id=vendor_id,
                year=year,
                annual_spend=spend_data["total_spend"],
                contract=ctr,
                currency=spend_data["currency"],
            )
            all_findings.extend(findings)

    # 4. Aggregate into risk scores
    from src.agents.report_generator import _aggregate_invoice_risk_scores
    risk_scores = _aggregate_invoice_risk_scores(all_findings, invoices)

    total_leakage = sum(s.total_leakage_amount for s in risk_scores)
    high_risk = sum(1 for s in risk_scores if s.overall_risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL))
    critical_risk = sum(1 for s in risk_scores if s.overall_risk_level == RiskLevel.CRITICAL)

    # 5. Executive summary
    inv_count = len(invoices)
    ctr_count = len(contracts_seen)
    currency = invoices[0]["currency"] if invoices else "AUD"
    summary = (
        f"Analysis completed at {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}. "
        f"Reviewed {inv_count} invoice(s) across {ctr_count} contract(s). "
        f"Total estimated leakage: {currency} {total_leakage:,.2f}. "
        f"{critical_risk} CRITICAL and {high_risk} HIGH risk invoice(s) identified requiring immediate action."
    )

    return AnalysisResult(
        analysis_id=f"ANLYS-{uuid.uuid4().hex[:8].upper()}",
        run_at=datetime.utcnow(),
        contracts_analysed=ctr_count,
        invoices_analysed=inv_count,
        total_leakage_amount=total_leakage,
        currency=currency,
        invoice_risk_scores=risk_scores,
        high_risk_count=high_risk,
        critical_risk_count=critical_risk,
        executive_summary=summary,
        detailed_findings=[LeakageFinding(**f) for f in all_findings],
    )


# ---------------------------------------------------------------------------
# Lifespan / startup
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Contract Leakage POC starting – sharepoint_mock=%s, bigquery_mock=%s",
        settings.sharepoint_mock_mode,
        settings.bigquery_mock_mode,
    )
    yield
    logger.info("Contract Leakage POC shutting down.")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Contract Leakage POC – Multi-Agent API",
    description=(
        "Multi-agent solution (Microsoft Azure AI Agent Service + AI Foundry) "
        "for detecting financial leakage between contracts (SharePoint) and "
        "invoices (GCP BigQuery)."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check() -> HealthResponse:
    """Return service health and mock-mode status."""
    return HealthResponse(
        status="ok",
        version="0.1.0",
        mock_mode={
            "sharepoint": settings.sharepoint_mock_mode,
            "bigquery": settings.bigquery_mock_mode,
        },
    )


@app.get("/schema/invoices", tags=["Schema"])
async def invoice_schema() -> JSONResponse:
    """Return the BigQuery invoice dataset schema (tables, fields, data types)."""
    from src.tools.bigquery_tools import get_invoice_schema

    return JSONResponse(content=get_invoice_schema())


@app.get("/contracts", tags=["Contracts"])
async def list_contracts(
    contract_type: str | None = None,
    vendor_id: str | None = None,
) -> JSONResponse:
    """List contracts from SharePoint (mock).

    Query params:
    - **contract_type**: ``supplier`` | ``customer`` | ``amendment`` | ``framework``
    - **vendor_id**: Filter by vendor/customer ID
    """
    from src.tools.sharepoint_tools import list_contracts as _list

    return JSONResponse(content=_list(contract_type=contract_type, supplier_or_customer_id=vendor_id))


@app.get("/contracts/{contract_id}", tags=["Contracts"])
async def get_contract(contract_id: str) -> JSONResponse:
    """Retrieve full details for a contract by ID."""
    from src.tools.sharepoint_tools import get_contract_details

    contract = get_contract_details(contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail=f"Contract {contract_id} not found.")
    return JSONResponse(content=contract)


@app.get("/invoices", tags=["Invoices"])
async def list_invoices(
    vendor_id: str | None = None,
    contract_id: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
) -> JSONResponse:
    """List invoices from BigQuery (mock).

    Query params:
    - **vendor_id**: Filter by vendor ID
    - **contract_id**: Filter by contract ID
    - **period_start**: ISO date (YYYY-MM-DD)
    - **period_end**: ISO date (YYYY-MM-DD)
    """
    from src.tools.bigquery_tools import get_invoices

    return JSONResponse(
        content=get_invoices(
            vendor_id=vendor_id,
            contract_id=contract_id,
            period_start=period_start,
            period_end=period_end,
        )
    )


@app.post("/analyse", response_model=AnalysisResult, tags=["Analysis"])
async def analyse(request: AnalysisRequest) -> AnalysisResult:
    """Run a full contract leakage analysis.

    In production, this triggers the Azure AI Foundry orchestrator agent.
    In mock/PoC mode, it runs the analysis locally using the tool layer directly.

    The response includes:
    - Executive summary
    - Per-invoice risk scores (ranked by risk)
    - Detailed leakage findings with evidence and recommendations
    - Total estimated leakage amount
    """
    if settings.azure_ai_project_connection_string:
        # Production path: delegate to Azure AI Foundry orchestrator
        try:
            from azure.identity import DefaultAzureCredential
            from azure.ai.projects import AIProjectClient
            from src.agents.orchestrator import create_orchestrator, run_analysis

            credential = DefaultAzureCredential()
            project_client = AIProjectClient(
                endpoint=settings.azure_ai_project_connection_string,
                credential=credential,
            )
            orchestrator = create_orchestrator(project_client)
            response_text = run_analysis(
                project_client=project_client,
                orchestrator=orchestrator,
                vendor_ids=request.vendor_ids,
                contract_ids=request.contract_ids,
                period_start=request.period_start.isoformat() if request.period_start else None,
                period_end=request.period_end.isoformat() if request.period_end else None,
                leakage_categories=[c.value for c in request.leakage_categories] if request.leakage_categories else None,
            )
            # Wrap plain-text response in an AnalysisResult for consistency
            return AnalysisResult(
                analysis_id=f"ANLYS-{uuid.uuid4().hex[:8].upper()}",
                contracts_analysed=0,
                invoices_analysed=0,
                total_leakage_amount=0,
                executive_summary=response_text,
            )
        except Exception as exc:
            logger.exception("Azure AI Foundry orchestrator failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    else:
        # PoC / demo path: local analysis
        logger.info("No Azure AI connection string – running local analysis.")
        return _run_local_analysis(request)
