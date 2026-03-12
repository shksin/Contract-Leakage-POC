"""Integration tests for the local analysis pipeline (FastAPI + tool layer)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.main import _run_local_analysis
from src.models.schemas import AnalysisRequest, RiskLevel


client = TestClient(app)


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_health_returns_ok(self):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "mock_mode" in data
        assert data["mock_mode"]["sharepoint"] is True
        assert data["mock_mode"]["bigquery"] is True


# ---------------------------------------------------------------------------
# Schema endpoint
# ---------------------------------------------------------------------------


class TestSchemaEndpoint:
    def test_invoice_schema_returned(self):
        response = client.get("/schema/invoices")
        assert response.status_code == 200
        data = response.json()
        assert "tables" in data
        assert "invoices" in data["tables"]
        assert "invoice_line_items" in data["tables"]


# ---------------------------------------------------------------------------
# Contracts endpoints
# ---------------------------------------------------------------------------


class TestContractsEndpoints:
    def test_list_all_contracts(self):
        response = client.get("/contracts")
        assert response.status_code == 200
        contracts = response.json()
        assert len(contracts) >= 4

    def test_list_supplier_contracts(self):
        response = client.get("/contracts?contract_type=supplier")
        assert response.status_code == 200
        contracts = response.json()
        assert all(c["contract_type"] == "supplier" for c in contracts)

    def test_get_contract_by_id(self):
        response = client.get("/contracts/CTR-2023-001")
        assert response.status_code == 200
        data = response.json()
        assert data["contract_id"] == "CTR-2023-001"

    def test_get_contract_not_found(self):
        response = client.get("/contracts/CTR-DOES-NOT-EXIST")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Invoices endpoints
# ---------------------------------------------------------------------------


class TestInvoicesEndpoints:
    def test_list_all_invoices(self):
        response = client.get("/invoices")
        assert response.status_code == 200
        invoices = response.json()
        assert len(invoices) >= 5

    def test_filter_by_vendor(self):
        response = client.get("/invoices?vendor_id=SUP-001")
        assert response.status_code == 200
        invoices = response.json()
        assert all(i["vendor_id"] == "SUP-001" for i in invoices)


# ---------------------------------------------------------------------------
# Analysis endpoint
# ---------------------------------------------------------------------------


class TestAnalyseEndpoint:
    def test_full_analysis_no_filters(self):
        response = client.post("/analyse", json={})
        assert response.status_code == 200
        result = response.json()
        assert "analysis_id" in result
        assert result["invoices_analysed"] >= 5
        assert result["total_leakage_amount"] > 0
        assert len(result["invoice_risk_scores"]) > 0
        assert len(result["detailed_findings"]) > 0

    def test_analysis_filtered_by_vendor(self):
        response = client.post("/analyse", json={"vendor_ids": ["SUP-001"]})
        assert response.status_code == 200
        result = response.json()
        # All risk scores should be for SUP-001 invoices
        for score in result["invoice_risk_scores"]:
            assert score["vendor_id"] == "SUP-001"

    def test_analysis_finds_expired_contract_risk(self):
        # Invoice INV-2024-00389 (SUP-002) references an expired contract
        response = client.post("/analyse", json={"vendor_ids": ["SUP-002"]})
        assert response.status_code == 200
        result = response.json()
        categories = [f["category"] for f in result["detailed_findings"]]
        assert "expired_terms_applied" in categories

    def test_analysis_finds_pricing_drift(self):
        # Invoice INV-2024-00215 (SUP-001) uses pre-amendment prices
        response = client.post("/analyse", json={"vendor_ids": ["SUP-001"]})
        assert response.status_code == 200
        result = response.json()
        categories = [f["category"] for f in result["detailed_findings"]]
        assert "pricing_drift" in categories

    def test_analysis_risk_scores_sorted_by_risk(self):
        response = client.post("/analyse", json={})
        assert response.status_code == 200
        result = response.json()
        scores = [s["risk_score"] for s in result["invoice_risk_scores"]]
        assert scores == sorted(scores, reverse=True)

    def test_analysis_has_executive_summary(self):
        response = client.post("/analyse", json={})
        assert response.status_code == 200
        result = response.json()
        assert len(result["executive_summary"]) > 0


# ---------------------------------------------------------------------------
# _run_local_analysis unit tests
# ---------------------------------------------------------------------------


class TestRunLocalAnalysis:
    def test_returns_analysis_result(self):
        req = AnalysisRequest()
        result = _run_local_analysis(req)
        assert result.invoices_analysed >= 5
        assert result.total_leakage_amount > 0

    def test_expired_contract_detection(self):
        req = AnalysisRequest(vendor_ids=["SUP-002"])
        result = _run_local_analysis(req)
        categories = [f.category.value for f in result.detailed_findings]
        assert "expired_terms_applied" in categories
        assert result.critical_risk_count > 0

    def test_pricing_drift_detection(self):
        req = AnalysisRequest(vendor_ids=["SUP-001"])
        result = _run_local_analysis(req)
        categories = [f.category.value for f in result.detailed_findings]
        assert "pricing_drift" in categories

    def test_missed_rebate_detection(self):
        req = AnalysisRequest()
        result = _run_local_analysis(req)
        categories = [f.category.value for f in result.detailed_findings]
        assert "missed_rebate" in categories

    def test_date_range_filter(self):
        req = AnalysisRequest(
            period_start=date(2024, 8, 1),
            period_end=date(2024, 8, 31),
        )
        result = _run_local_analysis(req)
        # Only August 2024 invoices should be analysed
        assert result.invoices_analysed >= 1

    def test_risk_scores_all_valid(self):
        req = AnalysisRequest()
        result = _run_local_analysis(req)
        for score in result.invoice_risk_scores:
            assert 0 <= score.risk_score <= 100
            assert score.overall_risk_level in RiskLevel.__members__.values()
