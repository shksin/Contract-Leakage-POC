"""Tests for leakage detection tools."""

from datetime import date

import pytest

from src.models.schemas import RiskLevel
from src.tools.leakage_tools import (
    _risk_from_variance,
    calculate_risk_score,
    check_contract_expiry,
    check_early_payment_discount,
    check_rebate_compliance,
    detect_pricing_drift,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def make_contract(
    contract_id="CTR-TEST-001",
    pricing_tiers=None,
    rebates=None,
    clauses=None,
    expiry_date="2025-12-31",
    effective_date="2023-01-01",
):
    return {
        "contract_id": contract_id,
        "currency": "AUD",
        "effective_date": effective_date,
        "expiry_date": expiry_date,
        "pricing_tiers": pricing_tiers or [],
        "rebates": rebates or [],
        "clauses": clauses or [],
    }


def make_invoice(
    invoice_id="INV-TEST-001",
    vendor_id="SUP-001",
    contract_id="CTR-TEST-001",
    invoice_date="2024-06-10",
    subtotal=840_000.0,
    total_amount=924_000.0,
    discount_applied=0.0,
    payment_date=None,
    line_items=None,
):
    return {
        "invoice_id": invoice_id,
        "vendor_id": vendor_id,
        "contract_id": contract_id,
        "invoice_date": invoice_date,
        "subtotal": subtotal,
        "tax_amount": 84_000.0,
        "discount_applied": discount_applied,
        "total_amount": total_amount,
        "currency": "AUD",
        "payment_date": payment_date,
        "due_date": "2024-07-10",
        "line_items": line_items or [],
    }


def make_line_item(
    line_item_id="LI-001",
    material_code="AN-BULK",
    description="Ammonium Nitrate",
    quantity=2000.0,
    unit_of_measure="MT",
    unit_price=420.0,
):
    return {
        "line_item_id": line_item_id,
        "material_code": material_code,
        "description": description,
        "quantity": quantity,
        "unit_of_measure": unit_of_measure,
        "unit_price": unit_price,
        "line_total": quantity * unit_price,
        "currency": "AUD",
    }


# ---------------------------------------------------------------------------
# _risk_from_variance
# ---------------------------------------------------------------------------


class TestRiskFromVariance:
    def test_critical(self):
        assert _risk_from_variance(20.0) == RiskLevel.CRITICAL

    def test_high(self):
        assert _risk_from_variance(10.0) == RiskLevel.HIGH

    def test_medium(self):
        assert _risk_from_variance(5.0) == RiskLevel.MEDIUM

    def test_low(self):
        assert _risk_from_variance(1.0) == RiskLevel.LOW

    def test_negative_variance(self):
        # Negative variance (overcharged) should also be CRITICAL if large
        assert _risk_from_variance(-20.0) == RiskLevel.CRITICAL


# ---------------------------------------------------------------------------
# detect_pricing_drift
# ---------------------------------------------------------------------------


class TestDetectPricingDrift:
    def test_no_drift_correct_price(self):
        contract = make_contract(
            pricing_tiers=[
                {"min_volume": 0, "max_volume": 500, "unit_price": 450.0},
                {"min_volume": 500, "max_volume": 2000, "unit_price": 420.0},
                {"min_volume": 2000, "max_volume": None, "unit_price": 390.0},
            ]
        )
        line_item = make_line_item(quantity=1950.0, unit_price=420.0)
        invoice = make_invoice(line_items=[line_item])
        findings = detect_pricing_drift(invoice, contract)
        assert findings == []

    def test_drift_detected_wrong_tier(self):
        # 2000 MT at tier 2 price (420) instead of tier 3 (390)
        contract = make_contract(
            pricing_tiers=[
                {"min_volume": 0, "max_volume": 500, "unit_price": 450.0},
                {"min_volume": 500, "max_volume": 2000, "unit_price": 420.0},
                {"min_volume": 2000, "max_volume": None, "unit_price": 390.0},
            ]
        )
        line_item = make_line_item(quantity=2000.0, unit_price=420.0)  # Should be 390
        invoice = make_invoice(line_items=[line_item])
        findings = detect_pricing_drift(invoice, contract)
        assert len(findings) == 1
        assert findings[0]["category"] == "pricing_drift"
        assert findings[0]["variance"] > 0  # Overcharged

    def test_drift_detected_amendment_price_not_applied(self):
        # Amendment price is 430 but invoice uses old price 420
        contract = make_contract(
            contract_id="CTR-2024-001A",
            pricing_tiers=[
                {"min_volume": 0, "max_volume": 500, "unit_price": 462.0},
                {"min_volume": 500, "max_volume": 2000, "unit_price": 430.0},
                {"min_volume": 2000, "max_volume": None, "unit_price": 399.0},
            ],
        )
        line_item = make_line_item(quantity=2000.0, unit_price=420.0)  # Should be 399
        invoice = make_invoice(line_items=[line_item])
        findings = detect_pricing_drift(invoice, contract)
        assert len(findings) == 1
        # Price too low for supplier (they should have charged 399 not 420)
        assert findings[0]["actual_value"] > findings[0]["expected_value"]

    def test_no_pricing_tiers_returns_empty(self):
        contract = make_contract(pricing_tiers=[])
        line_item = make_line_item(quantity=500.0, unit_price=450.0)
        invoice = make_invoice(line_items=[line_item])
        findings = detect_pricing_drift(invoice, contract)
        assert findings == []

    def test_finding_has_required_fields(self):
        contract = make_contract(
            pricing_tiers=[
                {"min_volume": 0, "max_volume": None, "unit_price": 450.0},
            ]
        )
        line_item = make_line_item(quantity=100.0, unit_price=500.0)  # 11% over
        invoice = make_invoice(line_items=[line_item])
        findings = detect_pricing_drift(invoice, contract)
        assert len(findings) == 1
        f = findings[0]
        assert "finding_id" in f
        assert "category" in f
        assert "risk_level" in f
        assert "description" in f
        assert "evidence" in f
        assert "recommendation" in f


# ---------------------------------------------------------------------------
# check_rebate_compliance
# ---------------------------------------------------------------------------


class TestCheckRebateCompliance:
    def test_rebate_triggered(self):
        contract = make_contract(
            rebates=[
                {
                    "rebate_type": "annual_volume_rebate",
                    "threshold": 5_000_000.0,
                    "rebate_percentage": 2.5,
                    "calculation_period": "annual",
                }
            ]
        )
        findings = check_rebate_compliance(
            vendor_id="SUP-001",
            year=2023,
            annual_spend=5_500_000.0,
            contract=contract,
            currency="AUD",
        )
        assert len(findings) == 1
        assert findings[0]["category"] == "missed_rebate"
        assert findings[0]["expected_value"] == pytest.approx(137_500.0)

    def test_below_threshold_no_finding(self):
        contract = make_contract(
            rebates=[
                {
                    "rebate_type": "annual_volume_rebate",
                    "threshold": 5_000_000.0,
                    "rebate_percentage": 2.5,
                    "calculation_period": "annual",
                }
            ]
        )
        findings = check_rebate_compliance(
            vendor_id="SUP-001",
            year=2023,
            annual_spend=4_000_000.0,
            contract=contract,
        )
        assert findings == []

    def test_quarterly_rebate_skipped_in_annual_check(self):
        contract = make_contract(
            rebates=[
                {
                    "rebate_type": "quarterly_volume_rebate",
                    "threshold": 2_000_000.0,
                    "rebate_percentage": 1.5,
                    "calculation_period": "quarterly",
                }
            ]
        )
        # Annual check should not trigger quarterly rebates
        findings = check_rebate_compliance(
            vendor_id="CUST-042",
            year=2024,
            annual_spend=10_000_000.0,
            contract=contract,
        )
        assert findings == []


# ---------------------------------------------------------------------------
# check_early_payment_discount
# ---------------------------------------------------------------------------


class TestCheckEarlyPaymentDiscount:
    def test_discount_not_applied_within_window(self):
        contract = make_contract(
            rebates=[
                {
                    "rebate_type": "early_payment_discount",
                    "threshold": 0,
                    "rebate_percentage": 1.0,
                    "calculation_period": "monthly",
                }
            ]
        )
        invoice = make_invoice(
            subtotal=546_000.0,
            discount_applied=0.0,
            invoice_date="2024-11-05",
            payment_date="2024-11-12",  # 7 days – within 10-day window
        )
        findings = check_early_payment_discount(invoice, contract)
        assert len(findings) == 1
        assert findings[0]["category"] == "missed_rebate"
        assert findings[0]["expected_value"] == pytest.approx(5460.0)

    def test_paid_late_no_discount_finding(self):
        contract = make_contract(
            rebates=[
                {
                    "rebate_type": "early_payment_discount",
                    "threshold": 0,
                    "rebate_percentage": 1.0,
                    "calculation_period": "monthly",
                }
            ]
        )
        invoice = make_invoice(
            subtotal=546_000.0,
            discount_applied=0.0,
            invoice_date="2024-11-05",
            payment_date="2024-12-01",  # 26 days – too late
        )
        findings = check_early_payment_discount(invoice, contract)
        assert findings == []

    def test_discount_already_applied(self):
        contract = make_contract(
            rebates=[
                {
                    "rebate_type": "early_payment_discount",
                    "threshold": 0,
                    "rebate_percentage": 1.0,
                    "calculation_period": "monthly",
                }
            ]
        )
        invoice = make_invoice(
            subtotal=546_000.0,
            discount_applied=5460.0,  # Already applied
            invoice_date="2024-11-05",
            payment_date="2024-11-12",
        )
        findings = check_early_payment_discount(invoice, contract)
        assert findings == []


# ---------------------------------------------------------------------------
# check_contract_expiry
# ---------------------------------------------------------------------------


class TestCheckContractExpiry:
    def test_expired_contract_flagged(self):
        contract = make_contract(expiry_date="2024-06-30")
        invoice = make_invoice(invoice_date="2024-08-15")  # After expiry
        findings = check_contract_expiry(invoice, contract)
        assert len(findings) == 1
        assert findings[0]["category"] == "expired_terms_applied"
        assert findings[0]["risk_level"] == "critical"

    def test_valid_contract_not_flagged(self):
        contract = make_contract(expiry_date="2025-12-31")
        invoice = make_invoice(invoice_date="2024-08-15")
        findings = check_contract_expiry(invoice, contract)
        assert findings == []

    def test_invoice_on_expiry_date_not_flagged(self):
        contract = make_contract(expiry_date="2024-06-30")
        invoice = make_invoice(invoice_date="2024-06-30")  # Same day as expiry
        findings = check_contract_expiry(invoice, contract)
        assert findings == []


# ---------------------------------------------------------------------------
# calculate_risk_score
# ---------------------------------------------------------------------------


class TestCalculateRiskScore:
    def test_empty_findings_zero_score(self):
        assert calculate_risk_score([]) == 0.0

    def test_single_critical_finding(self):
        findings = [{"risk_level": "critical"}]
        assert calculate_risk_score(findings) == 40.0

    def test_single_high_finding(self):
        findings = [{"risk_level": "high"}]
        assert calculate_risk_score(findings) == 20.0

    def test_capped_at_100(self):
        findings = [{"risk_level": "critical"}] * 10
        assert calculate_risk_score(findings) == 100.0

    def test_mixed_findings(self):
        findings = [
            {"risk_level": "critical"},
            {"risk_level": "high"},
            {"risk_level": "medium"},
        ]
        score = calculate_risk_score(findings)
        assert score == 70.0  # 40 + 20 + 10
