"""Leakage analysis tools.

Pure-Python functions that implement the leakage detection logic.
These are called by the Leakage Detector Agent as function tools.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

from src.models.schemas import (
    LeakageCategory,
    LeakageFinding,
    RiskLevel,
)

logger = logging.getLogger(__name__)


def _risk_from_variance(variance_pct: float) -> RiskLevel:
    """Map a variance percentage to a risk level."""
    abs_pct = abs(variance_pct)
    if abs_pct >= 15:
        return RiskLevel.CRITICAL
    if abs_pct >= 8:
        return RiskLevel.HIGH
    if abs_pct >= 3:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def detect_pricing_drift(
    invoice: dict,
    contract: dict,
) -> list[dict]:
    """Detect unit-price discrepancies between invoice line items and contract pricing tiers.

    Compares each invoice line item's ``unit_price`` against the correct
    volume-tiered rate from the active contract.

    Args:
        invoice: Invoice dict (as returned by BigQuery tools).
        contract: Active contract dict (as returned by SharePoint tools).

    Returns:
        List of LeakageFinding dicts (may be empty if no drift found).
    """
    findings: list[LeakageFinding] = []
    pricing_tiers = contract.get("pricing_tiers", [])

    if not pricing_tiers:
        return []

    for item in invoice.get("line_items", []):
        quantity = float(item.get("quantity", 0))
        invoiced_price = float(item.get("unit_price", 0))

        # Find the correct tier
        correct_price: float | None = None
        for tier in pricing_tiers:
            min_v = float(tier.get("min_volume", 0))
            max_v = tier.get("max_volume")
            if max_v is not None:
                max_v = float(max_v)
            if quantity >= min_v and (max_v is None or quantity < max_v):
                correct_price = float(tier.get("unit_price", 0))
                break

        if correct_price is None or invoiced_price == correct_price:
            continue

        variance = (invoiced_price - correct_price) * quantity
        variance_pct = ((invoiced_price - correct_price) / correct_price) * 100 if correct_price else 0

        finding = LeakageFinding(
            finding_id=f"FIND-{uuid.uuid4().hex[:8].upper()}",
            invoice_id=invoice["invoice_id"],
            contract_id=contract.get("contract_id"),
            category=LeakageCategory.PRICING_DRIFT,
            risk_level=_risk_from_variance(variance_pct),
            description=(
                f"Unit price on invoice ({invoice['invoice_id']}) for "
                f"'{item.get('description', item.get('material_code'))}' is "
                f"{invoice.get('currency','AUD')} {invoiced_price:.2f}/unit but the active "
                f"contract ({contract.get('contract_id')}) specifies "
                f"{contract.get('currency','AUD')} {correct_price:.2f}/unit for "
                f"qty {quantity} {item.get('unit_of_measure','units')}."
            ),
            expected_value=correct_price * quantity,
            actual_value=invoiced_price * quantity,
            variance=variance,
            variance_percentage=round(variance_pct, 2),
            evidence=(
                f"Contract clause: {_find_clause_description(contract, 'pricing')}. "
                f"Invoice line item: {item.get('material_code')} × {quantity} {item.get('unit_of_measure','units')}."
            ),
            recommendation=(
                "Raise a credit / debit note for the difference. "
                f"Expected total: {contract.get('currency','AUD')} {correct_price * quantity:,.2f}, "
                f"invoiced: {invoice.get('currency','AUD')} {invoiced_price * quantity:,.2f}. "
                f"Discrepancy: {invoice.get('currency','AUD')} {variance:,.2f}."
            ),
        )
        findings.append(finding)
        logger.info("Pricing drift detected: %s (variance %.1f%%)", finding.finding_id, variance_pct)

    return [f.model_dump(mode="json") for f in findings]


def check_rebate_compliance(
    vendor_id: str,
    year: int,
    annual_spend: float,
    contract: dict,
    currency: str = "AUD",
) -> list[dict]:
    """Check whether applicable rebates have been claimed.

    Args:
        vendor_id: Vendor identifier.
        year: Calendar year being assessed.
        annual_spend: Total spend with the vendor in that year.
        contract: Contract dict containing ``rebates`` list.
        currency: Currency of the spend figure.

    Returns:
        List of LeakageFinding dicts for unclaimed rebates.
    """
    findings: list[LeakageFinding] = []
    for rebate in contract.get("rebates", []):
        rebate_type = rebate.get("rebate_type", "")
        threshold = float(rebate.get("threshold", 0))
        pct = float(rebate.get("rebate_percentage", 0))
        period = rebate.get("calculation_period", "annual")

        if period != "annual":
            continue  # Quarterly/monthly rebates are checked elsewhere

        if annual_spend >= threshold:
            expected_rebate = annual_spend * (pct / 100)
            finding = LeakageFinding(
                finding_id=f"FIND-{uuid.uuid4().hex[:8].upper()}",
                invoice_id="ANNUAL-REBATE-CHECK",
                contract_id=contract.get("contract_id"),
                category=LeakageCategory.MISSED_REBATE,
                risk_level=RiskLevel.HIGH,
                description=(
                    f"Vendor {vendor_id} annual spend in {year} ({currency} {annual_spend:,.2f}) "
                    f"exceeds the {rebate_type} threshold ({currency} {threshold:,.2f}). "
                    f"Expected rebate of {pct}% ({currency} {expected_rebate:,.2f}) "
                    f"does not appear to have been credited."
                ),
                expected_value=expected_rebate,
                actual_value=0.0,
                variance=-expected_rebate,
                variance_percentage=-pct,
                evidence=_find_clause_description(contract, "rebate"),
                recommendation=(
                    f"Request a {currency} {expected_rebate:,.2f} credit note from vendor {vendor_id} "
                    f"for the {year} annual volume rebate per contract {contract.get('contract_id')}."
                ),
            )
            findings.append(finding)
            logger.info("Missed rebate detected: %s", finding.finding_id)

    return [f.model_dump(mode="json") for f in findings]


def check_early_payment_discount(invoice: dict, contract: dict) -> list[dict]:
    """Identify invoices paid within the early-payment window but without the discount applied.

    Args:
        invoice: Invoice dict.
        contract: Contract dict.

    Returns:
        List of LeakageFinding dicts.
    """
    findings: list[LeakageFinding] = []
    payment_date_str = invoice.get("payment_date")
    invoice_date_str = invoice.get("invoice_date")
    due_date_str = invoice.get("due_date")

    if not payment_date_str or not invoice_date_str:
        return []

    payment_date = date.fromisoformat(str(payment_date_str))
    invoice_date = date.fromisoformat(str(invoice_date_str))
    days_to_pay = (payment_date - invoice_date).days

    for rebate in contract.get("rebates", []):
        if rebate.get("rebate_type") != "early_payment_discount":
            continue
        pct = float(rebate.get("rebate_percentage", 0))
        # Convention: early payment window = 10 days
        if days_to_pay <= 10:
            discount_entitled = invoice["subtotal"] * (pct / 100)
            if float(invoice.get("discount_applied", 0)) < discount_entitled * 0.99:
                finding = LeakageFinding(
                    finding_id=f"FIND-{uuid.uuid4().hex[:8].upper()}",
                    invoice_id=invoice["invoice_id"],
                    contract_id=contract.get("contract_id"),
                    category=LeakageCategory.MISSED_REBATE,
                    risk_level=RiskLevel.MEDIUM,
                    description=(
                        f"Invoice {invoice['invoice_id']} was paid within {days_to_pay} days "
                        f"(qualifying for {pct}% early payment discount), but the discount of "
                        f"{invoice.get('currency','AUD')} {discount_entitled:,.2f} was not applied."
                    ),
                    expected_value=discount_entitled,
                    actual_value=float(invoice.get("discount_applied", 0)),
                    variance=float(invoice.get("discount_applied", 0)) - discount_entitled,
                    variance_percentage=round(-pct, 2),
                    evidence=_find_clause_description(contract, "payment_terms"),
                    recommendation=(
                        f"Claim a credit note of {invoice.get('currency','AUD')} {discount_entitled:,.2f} "
                        f"from vendor for early payment discount on invoice {invoice['invoice_id']}."
                    ),
                )
                findings.append(finding)
    return [f.model_dump(mode="json") for f in findings]


def validate_volume_tiers(invoice: dict, contract: dict) -> list[dict]:
    """Detect incorrect pricing tier application due to order-splitting or tier misclassification.

    This function checks for the customer-invoice scenario where a large
    single-order quantity should attract a lower tier price but a higher
    tier price was charged instead (or vice-versa for supplier invoices).

    Args:
        invoice: Invoice dict.
        contract: Contract dict.

    Returns:
        List of LeakageFinding dicts.
    """
    # Pricing-drift detection already handles unit-price discrepancies.
    # This function provides the explicit volume-tier narrative.
    return detect_pricing_drift(invoice, contract)


def check_contract_expiry(invoice: dict, contract: dict) -> list[dict]:
    """Flag invoices where the referenced contract was expired at invoice date.

    Args:
        invoice: Invoice dict.
        contract: Contract dict.

    Returns:
        List of LeakageFinding dicts.
    """
    findings: list[LeakageFinding] = []
    invoice_date_str = invoice.get("invoice_date")
    expiry_date_str = contract.get("expiry_date")

    if not invoice_date_str or not expiry_date_str:
        return []

    invoice_date = date.fromisoformat(str(invoice_date_str))
    expiry_date = date.fromisoformat(str(expiry_date_str))

    if invoice_date > expiry_date:
        finding = LeakageFinding(
            finding_id=f"FIND-{uuid.uuid4().hex[:8].upper()}",
            invoice_id=invoice["invoice_id"],
            contract_id=contract.get("contract_id"),
            category=LeakageCategory.EXPIRED_TERMS_APPLIED,
            risk_level=RiskLevel.CRITICAL,
            description=(
                f"Invoice {invoice['invoice_id']} (dated {invoice_date}) references contract "
                f"{contract.get('contract_id')} which expired on {expiry_date}. "
                "Invoicing under expired contract terms carries compliance and financial risk."
            ),
            expected_value=None,
            actual_value=float(invoice.get("total_amount", 0)),
            variance=None,
            variance_percentage=None,
            evidence=_find_clause_description(contract, "expiry"),
            recommendation=(
                f"Verify whether a renewed or replacement contract exists for vendor "
                f"{invoice.get('vendor_id')}. If not, halt further invoicing until a "
                "new contract is executed. Escalate to Procurement and Legal."
            ),
        )
        findings.append(finding)
        logger.info("Expired contract detected: invoice=%s, contract=%s", invoice["invoice_id"], contract.get("contract_id"))

    return [f.model_dump(mode="json") for f in findings]


def calculate_risk_score(findings: list[dict]) -> float:
    """Compute a 0–100 risk score from a list of LeakageFinding dicts.

    Weights: CRITICAL=40, HIGH=20, MEDIUM=10, LOW=5.
    Score is capped at 100.

    Args:
        findings: List of LeakageFinding dicts.

    Returns:
        Float risk score in [0, 100].
    """
    weight_map = {
        RiskLevel.CRITICAL: 40,
        RiskLevel.HIGH: 20,
        RiskLevel.MEDIUM: 10,
        RiskLevel.LOW: 5,
    }
    score = 0.0
    for f in findings:
        level_str = f.get("risk_level", "low")
        try:
            level = RiskLevel(level_str)
        except ValueError:
            level = RiskLevel.LOW
        score += weight_map[level]
    return min(score, 100.0)


def _find_clause_description(contract: dict, clause_type: str) -> str:
    """Extract the first matching clause description for evidence text."""
    for clause in contract.get("clauses", []):
        if clause.get("clause_type") == clause_type:
            return clause.get("description", "")
    return "No matching clause found in contract."
