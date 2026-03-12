"""Tests for data models (src/models/schemas.py)."""

from datetime import date, datetime

import pytest

from src.models.schemas import (
    AnalysisRequest,
    AnalysisResult,
    Contract,
    ContractClause,
    ContractType,
    Invoice,
    InvoiceLineItem,
    InvoiceRiskScore,
    LeakageCategory,
    LeakageFinding,
    PricingTier,
    RebateStructure,
    RiskLevel,
)


class TestPricingTier:
    def test_basic_creation(self):
        tier = PricingTier(min_volume=0, max_volume=500, unit_price=450.0)
        assert tier.unit_price == 450.0
        assert tier.currency == "USD"

    def test_unlimited_max_volume(self):
        tier = PricingTier(min_volume=2000, max_volume=None, unit_price=390.0)
        assert tier.max_volume is None


class TestRebateStructure:
    def test_creation(self):
        rebate = RebateStructure(
            rebate_type="annual_volume_rebate",
            threshold=5_000_000,
            rebate_percentage=2.5,
        )
        assert rebate.calculation_period == "annual"
        assert rebate.rebate_percentage == 2.5


class TestContract:
    def test_full_contract(self):
        contract = Contract(
            contract_id="CTR-TEST-001",
            contract_type=ContractType.SUPPLIER,
            supplier_or_customer_id="SUP-001",
            supplier_or_customer_name="Test Supplier",
            contract_name="Test Agreement",
            effective_date=date(2023, 1, 1),
            expiry_date=date(2025, 12, 31),
            currency="AUD",
        )
        assert contract.contract_type == ContractType.SUPPLIER
        assert len(contract.pricing_tiers) == 0
        assert len(contract.rebates) == 0

    def test_serialisation(self):
        contract = Contract(
            contract_id="CTR-TEST-002",
            contract_type=ContractType.CUSTOMER,
            supplier_or_customer_id="CUST-001",
            supplier_or_customer_name="Test Customer",
            contract_name="Customer Agreement",
            effective_date=date(2024, 1, 1),
            expiry_date=date(2026, 12, 31),
        )
        data = contract.model_dump(mode="json")
        assert data["contract_id"] == "CTR-TEST-002"
        assert data["effective_date"] == "2024-01-01"
        assert data["expiry_date"] == "2026-12-31"


class TestInvoice:
    def test_basic_invoice(self):
        inv = Invoice(
            invoice_id="INV-001",
            vendor_id="SUP-001",
            vendor_name="Test Vendor",
            subtotal=1000.0,
            tax_amount=100.0,
            total_amount=1100.0,
            invoice_date=date(2024, 3, 15),
        )
        assert inv.discount_applied == 0.0
        assert inv.currency == "USD"

    def test_invoice_with_line_items(self):
        inv = Invoice(
            invoice_id="INV-002",
            vendor_id="SUP-001",
            vendor_name="Test Vendor",
            subtotal=840_000.0,
            tax_amount=84_000.0,
            total_amount=924_000.0,
            invoice_date=date(2024, 6, 10),
            line_items=[
                InvoiceLineItem(
                    line_item_id="LI-001",
                    material_code="AN-BULK",
                    description="Ammonium Nitrate",
                    quantity=2000.0,
                    unit_of_measure="MT",
                    unit_price=420.0,
                    line_total=840_000.0,
                    currency="AUD",
                )
            ],
        )
        assert len(inv.line_items) == 1
        assert inv.line_items[0].unit_price == 420.0


class TestLeakageFinding:
    def test_creation(self):
        finding = LeakageFinding(
            finding_id="FIND-001",
            invoice_id="INV-001",
            contract_id="CTR-001",
            category=LeakageCategory.PRICING_DRIFT,
            risk_level=RiskLevel.HIGH,
            description="Unit price discrepancy detected.",
            expected_value=430.0,
            actual_value=420.0,
            variance=-10.0,
            variance_percentage=-2.33,
        )
        assert finding.category == LeakageCategory.PRICING_DRIFT
        assert finding.risk_level == RiskLevel.HIGH
        assert finding.variance == -10.0

    def test_all_leakage_categories(self):
        for cat in LeakageCategory:
            finding = LeakageFinding(
                finding_id=f"FIND-{cat.value}",
                invoice_id="INV-001",
                contract_id=None,
                category=cat,
                risk_level=RiskLevel.LOW,
                description=f"Test {cat.value}",
            )
            assert finding.category == cat


class TestAnalysisRequest:
    def test_empty_request(self):
        req = AnalysisRequest()
        assert req.vendor_ids is None
        assert req.contract_ids is None
        assert req.period_start is None

    def test_filtered_request(self):
        req = AnalysisRequest(
            vendor_ids=["SUP-001"],
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
        )
        assert req.vendor_ids == ["SUP-001"]
        assert req.period_start == date(2024, 1, 1)


class TestAnalysisResult:
    def test_creation(self):
        result = AnalysisResult(
            analysis_id="ANLYS-001",
            contracts_analysed=4,
            invoices_analysed=5,
            total_leakage_amount=125_000.0,
            currency="AUD",
        )
        assert result.high_risk_count == 0
        assert result.critical_risk_count == 0
        assert isinstance(result.run_at, datetime)
