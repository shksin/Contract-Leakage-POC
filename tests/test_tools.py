"""Tests for SharePoint and BigQuery tool functions."""

from datetime import date

import pytest

from src.tools.bigquery_tools import (
    get_invoice_by_id,
    get_invoice_schema,
    get_invoices,
    get_vendor_annual_spend,
)
from src.tools.sharepoint_tools import (
    get_active_contract_on_date,
    get_contract_details,
    get_contracts_for_vendor,
    list_contracts,
)


# ---------------------------------------------------------------------------
# SharePoint tools
# ---------------------------------------------------------------------------


class TestListContracts:
    def test_returns_all_contracts(self):
        contracts = list_contracts()
        assert len(contracts) >= 4

    def test_filter_by_type_supplier(self):
        contracts = list_contracts(contract_type="supplier")
        assert all(c["contract_type"] == "supplier" for c in contracts)
        assert len(contracts) >= 2

    def test_filter_by_type_amendment(self):
        contracts = list_contracts(contract_type="amendment")
        assert all(c["contract_type"] == "amendment" for c in contracts)

    def test_filter_by_vendor(self):
        contracts = list_contracts(supplier_or_customer_id="SUP-001")
        assert all(c["supplier_or_customer_id"] == "SUP-001" for c in contracts)

    def test_returns_required_fields(self):
        contracts = list_contracts()
        for c in contracts:
            assert "contract_id" in c
            assert "effective_date" in c
            assert "expiry_date" in c


class TestGetContractDetails:
    def test_existing_contract(self):
        contract = get_contract_details("CTR-2023-001")
        assert contract is not None
        assert contract["contract_id"] == "CTR-2023-001"
        assert len(contract["pricing_tiers"]) == 3
        assert len(contract["rebates"]) == 2

    def test_nonexistent_contract(self):
        contract = get_contract_details("CTR-DOES-NOT-EXIST")
        assert contract is None

    def test_contract_has_clauses(self):
        contract = get_contract_details("CTR-2023-001")
        assert contract is not None
        assert len(contract["clauses"]) > 0
        clause_types = [c["clause_type"] for c in contract["clauses"]]
        assert "pricing" in clause_types


class TestGetContractsForVendor:
    def test_sup_001_has_multiple_contracts(self):
        contracts = get_contracts_for_vendor("SUP-001")
        assert len(contracts) >= 2  # Original + amendment

    def test_sorted_by_effective_date(self):
        contracts = get_contracts_for_vendor("SUP-001")
        dates = [c["effective_date"] for c in contracts]
        assert dates == sorted(dates)

    def test_unknown_vendor_returns_empty(self):
        contracts = get_contracts_for_vendor("SUP-UNKNOWN")
        assert contracts == []


class TestGetActiveContractOnDate:
    def test_active_contract_found(self):
        contract = get_active_contract_on_date("SUP-001", "2024-06-15")
        assert contract is not None

    def test_amendment_preferred_over_original(self):
        # Amendment CTR-2024-001A effective 2024-01-01 should be returned for 2024 dates
        contract = get_active_contract_on_date("SUP-001", "2024-06-15")
        assert contract is not None
        # Should return the amendment (later effective date)
        assert contract["effective_date"] >= "2024-01-01"

    def test_expired_contract_not_returned(self):
        # CTR-2022-018 expired 2024-06-30; a date after expiry should return None
        contract = get_active_contract_on_date("SUP-002", "2024-08-15")
        assert contract is None

    def test_before_any_contract_returns_none(self):
        contract = get_active_contract_on_date("SUP-001", "2020-01-01")
        assert contract is None

    def test_unknown_vendor_returns_none(self):
        contract = get_active_contract_on_date("SUP-UNKNOWN", "2024-01-01")
        assert contract is None


# ---------------------------------------------------------------------------
# BigQuery tools
# ---------------------------------------------------------------------------


class TestGetInvoiceSchema:
    def test_schema_has_both_tables(self):
        schema = get_invoice_schema()
        assert "invoices" in schema["tables"]
        assert "invoice_line_items" in schema["tables"]

    def test_invoices_table_has_required_fields(self):
        schema = get_invoice_schema()
        fields = schema["tables"]["invoices"]["fields"]
        assert "invoice_id" in fields
        assert "vendor_id" in fields
        assert "total_amount" in fields
        assert "invoice_date" in fields

    def test_key_identifiers_and_monetary_fields(self):
        schema = get_invoice_schema()
        inv_table = schema["tables"]["invoices"]
        assert "invoice_id" in inv_table["key_identifiers"]
        assert "total_amount" in inv_table["monetary_fields"]
        assert "invoice_date" in inv_table["timestamps"]


class TestGetInvoices:
    def test_returns_all_invoices(self):
        invoices = get_invoices()
        assert len(invoices) >= 5

    def test_filter_by_vendor(self):
        invoices = get_invoices(vendor_id="SUP-001")
        assert all(i["vendor_id"] == "SUP-001" for i in invoices)
        assert len(invoices) >= 3

    def test_filter_by_contract(self):
        invoices = get_invoices(contract_id="CTR-2023-001")
        assert all(i.get("contract_id") == "CTR-2023-001" for i in invoices)

    def test_filter_by_date_range(self):
        invoices = get_invoices(period_start="2024-06-01", period_end="2024-07-31")
        for inv in invoices:
            inv_date = date.fromisoformat(str(inv["invoice_date"]))
            assert date(2024, 6, 1) <= inv_date <= date(2024, 7, 31)

    def test_invoices_include_line_items(self):
        invoices = get_invoices()
        for inv in invoices:
            assert "line_items" in inv


class TestGetInvoiceById:
    def test_existing_invoice(self):
        inv = get_invoice_by_id("INV-2024-00101")
        assert inv is not None
        assert inv["invoice_id"] == "INV-2024-00101"

    def test_nonexistent_invoice(self):
        inv = get_invoice_by_id("INV-DOES-NOT-EXIST")
        assert inv is None


class TestGetVendorAnnualSpend:
    def test_sup_001_2024_spend(self):
        result = get_vendor_annual_spend("SUP-001", 2024)
        assert result["vendor_id"] == "SUP-001"
        assert result["year"] == 2024
        assert result["total_spend"] > 0
        assert result["invoice_count"] >= 3

    def test_no_invoices_returns_zero(self):
        result = get_vendor_annual_spend("SUP-UNKNOWN", 2024)
        assert result["total_spend"] == 0
        assert result["invoice_count"] == 0
