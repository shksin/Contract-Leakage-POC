"""Pydantic data models for Contract Leakage POC.

Covers contracts, invoices, leakage findings, and analysis results.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ContractType(str, Enum):
    """Supported contract categories."""

    SUPPLIER = "supplier"
    CUSTOMER = "customer"
    AMENDMENT = "amendment"
    FRAMEWORK = "framework"


class RiskLevel(str, Enum):
    """Risk severity for leakage findings."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class LeakageCategory(str, Enum):
    """Categories of contract leakage."""

    PRICING_DRIFT = "pricing_drift"
    MISSED_REBATE = "missed_rebate"
    VOLUME_TIER_BREACH = "volume_tier_breach"
    EXPIRED_TERMS_APPLIED = "expired_terms_applied"
    PAYMENT_TERMS_VIOLATION = "payment_terms_violation"
    INCORRECT_CURRENCY = "incorrect_currency"


# ---------------------------------------------------------------------------
# Contract Models
# ---------------------------------------------------------------------------


class PricingTier(BaseModel):
    """Volume-based pricing tier within a contract."""

    min_volume: float = Field(..., description="Minimum volume for this tier")
    max_volume: float | None = Field(None, description="Maximum volume (None = unlimited)")
    unit_price: float = Field(..., description="Unit price for this tier")
    currency: str = Field(default="USD", description="ISO 4217 currency code")


class RebateStructure(BaseModel):
    """Rebate or discount structure defined in a contract."""

    rebate_type: str = Field(..., description="e.g. volume_rebate, early_payment, annual_target")
    threshold: float = Field(..., description="Purchase threshold to trigger rebate")
    rebate_percentage: float = Field(..., description="Rebate as percentage of spend (0-100)")
    calculation_period: str = Field(default="annual", description="annual | quarterly | monthly")


class ContractClause(BaseModel):
    """A key clause extracted from a contract document."""

    clause_type: str = Field(..., description="e.g. pricing, rebate, volume_tier, expiry, payment_terms")
    description: str = Field(..., description="Human-readable clause description")
    effective_date: date | None = Field(None, description="Date clause becomes effective")
    expiry_date: date | None = Field(None, description="Date clause expires")
    value: dict[str, Any] = Field(default_factory=dict, description="Structured clause data")


class Contract(BaseModel):
    """Represents a supplier or customer contract sourced from SharePoint."""

    contract_id: str = Field(..., description="Unique contract identifier")
    contract_type: ContractType
    supplier_or_customer_id: str = Field(..., description="Party identifier (vendor/customer code)")
    supplier_or_customer_name: str
    contract_name: str
    effective_date: date
    expiry_date: date
    currency: str = Field(default="USD")
    pricing_tiers: list[PricingTier] = Field(default_factory=list)
    rebates: list[RebateStructure] = Field(default_factory=list)
    clauses: list[ContractClause] = Field(default_factory=list)
    sharepoint_url: str = Field(default="", description="Source document URL")
    raw_text_excerpt: str = Field(default="", description="Excerpt from the source document")


# ---------------------------------------------------------------------------
# Invoice / BigQuery Models  (GCP schema)
# ---------------------------------------------------------------------------


class InvoiceLineItem(BaseModel):
    """A single line item on an invoice (BigQuery: invoice_line_items table)."""

    line_item_id: str
    material_code: str = Field(..., description="Product / material identifier")
    description: str
    quantity: float
    unit_of_measure: str
    unit_price: float
    line_total: float
    currency: str = Field(default="USD")


class Invoice(BaseModel):
    """Invoice record sourced from BigQuery (GCP).

    Physical table: ``finance_data.invoices``
    """

    # Key identifiers
    invoice_id: str = Field(..., description="PK – unique invoice number")
    purchase_order_id: str | None = Field(None, description="FK – linked PO number")
    vendor_id: str = Field(..., description="FK – vendor / supplier code")
    vendor_name: str
    contract_id: str | None = Field(None, description="FK – linked contract ID (may be NULL)")

    # Monetary fields
    subtotal: float = Field(..., description="Sum of line items before tax/rebate")
    tax_amount: float = Field(default=0.0)
    discount_applied: float = Field(default=0.0)
    total_amount: float = Field(..., description="Final invoiced amount")
    currency: str = Field(default="USD")

    # Timestamps
    invoice_date: date = Field(..., description="Date printed on invoice")
    service_period_start: date | None = Field(None, description="Service / delivery start")
    service_period_end: date | None = Field(None, description="Service / delivery end")
    due_date: date | None = None
    payment_date: date | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Line items
    line_items: list[InvoiceLineItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Leakage / Analysis Models
# ---------------------------------------------------------------------------


class LeakageFinding(BaseModel):
    """A single leakage finding for a given invoice."""

    finding_id: str
    invoice_id: str
    contract_id: str | None
    category: LeakageCategory
    risk_level: RiskLevel
    description: str = Field(..., description="Plain-language description of the finding")
    expected_value: float | None = Field(None, description="What the contract dictates")
    actual_value: float | None = Field(None, description="What was invoiced")
    variance: float | None = Field(None, description="actual_value - expected_value")
    variance_percentage: float | None = Field(None, description="variance as % of expected")
    evidence: str = Field(default="", description="Supporting clause text or data points")
    recommendation: str = Field(default="", description="Suggested remediation action")


class InvoiceRiskScore(BaseModel):
    """Aggregated risk score for a single invoice."""

    invoice_id: str
    vendor_id: str
    vendor_name: str
    contract_id: str | None
    overall_risk_level: RiskLevel
    risk_score: float = Field(..., ge=0, le=100, description="0=no risk, 100=maximum risk")
    total_leakage_amount: float = Field(default=0.0, description="Total monetary leakage identified")
    currency: str = Field(default="USD")
    findings: list[LeakageFinding] = Field(default_factory=list)
    summary: str = Field(default="")


class AnalysisResult(BaseModel):
    """Top-level result returned by the Orchestrator Agent."""

    analysis_id: str
    run_at: datetime = Field(default_factory=datetime.utcnow)
    contracts_analysed: int
    invoices_analysed: int
    total_leakage_amount: float
    currency: str = Field(default="USD")
    invoice_risk_scores: list[InvoiceRiskScore] = Field(default_factory=list)
    high_risk_count: int = 0
    critical_risk_count: int = 0
    executive_summary: str = Field(default="")
    detailed_findings: list[LeakageFinding] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API Request / Response Models
# ---------------------------------------------------------------------------


class AnalysisRequest(BaseModel):
    """Request body for the /analyse endpoint."""

    vendor_ids: list[str] | None = Field(
        None,
        description="Limit analysis to these vendor IDs. Omit to analyse all.",
    )
    contract_ids: list[str] | None = Field(
        None,
        description="Limit analysis to these contract IDs. Omit to analyse all.",
    )
    period_start: date | None = Field(None, description="Invoice date range start (inclusive)")
    period_end: date | None = Field(None, description="Invoice date range end (inclusive)")
    leakage_categories: list[LeakageCategory] | None = Field(
        None,
        description="Specific leakage categories to check. Omit for all.",
    )


class HealthResponse(BaseModel):
    """Health-check response."""

    status: str = "ok"
    version: str = "0.1.0"
    mock_mode: dict[str, bool] = Field(default_factory=dict)
