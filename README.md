# Contract Leakage POC – Multi-Agent Solution

> **Proof of Concept** for Orica's Contract Leakage Detection using the **Microsoft Azure AI Agent Service** (Azure AI Foundry) with a multi-agent architecture.

---

## Overview

This solution automatically detects financial leakage between supplier/customer contracts (sourced from **SharePoint**) and invoice data (sourced from **GCP BigQuery**). It uses a team of specialised AI agents orchestrated by a central coordinator.

### Leakage Scenarios Detected

| Category | Description | Risk |
|---|---|---|
| **Pricing Drift** | Invoice unit price deviates from contracted volume-tier rate | HIGH–CRITICAL |
| **Missed Rebate** | Annual/quarterly volume threshold met but no rebate credit applied | HIGH |
| **Early Payment Discount Omitted** | Invoice paid within discount window but 1% discount not taken | MEDIUM |
| **Expired Contract Terms Applied** | Invoice dated after contract expiry, no valid agreement in place | CRITICAL |
| **Volume Tier Breach** | Wrong pricing tier applied for order quantity | HIGH–CRITICAL |

---

## Architecture

```
User / REST API
      │
      ▼
┌─────────────────────────────────────────────────────┐
│          OrchestratorAgent (Azure AI Foundry)        │
│  Coordinates workflow, aggregates findings           │
└───┬──────────────┬───────────────┬──────────────────┘
    │              │               │               │
    ▼              ▼               ▼               ▼
ContractAgent  InvoiceAgent  LeakageDetector  ReportGenerator
(SharePoint)   (BigQuery/GCP)  (Analysis)      (Reports)
```

### Agents

| Agent | Responsibility | Data Source |
|---|---|---|
| **ContractAgent** | Retrieve & parse contracts (pricing tiers, rebates, clauses, expiry) | SharePoint (mock) |
| **InvoiceAgent** | Retrieve invoice data with line-item detail | GCP BigQuery (mock) |
| **LeakageDetectorAgent** | Run all leakage checks, calculate risk scores | Local analysis tools |
| **ReportGeneratorAgent** | Build executive summary, risk tables, recommendations | Analysis results |
| **OrchestratorAgent** | Coordinate the full workflow end-to-end | All agents via Connected Agent Tools |

---

## Project Structure

```
.
├── src/
│   ├── agents/
│   │   ├── contract_agent.py      # SharePoint contract retrieval agent
│   │   ├── invoice_agent.py       # BigQuery invoice agent
│   │   ├── leakage_detector.py    # Leakage detection agent
│   │   ├── report_generator.py    # Report generation agent
│   │   └── orchestrator.py        # Master orchestrator (Connected Agents)
│   ├── tools/
│   │   ├── sharepoint_tools.py    # SharePoint integration (mock in PoC)
│   │   ├── bigquery_tools.py      # BigQuery/GCP integration (mock in PoC)
│   │   └── leakage_tools.py       # Leakage detection logic
│   ├── models/
│   │   └── schemas.py             # Pydantic data models
│   ├── config.py                  # App configuration
│   └── main.py                    # FastAPI entry point
├── sample_data/
│   └── mock_data.py               # Representative contracts & invoices
├── tests/
│   ├── test_models.py             # Data model tests
│   ├── test_tools.py              # SharePoint & BigQuery tool tests
│   ├── test_leakage_tools.py      # Leakage detection logic tests
│   └── test_analysis.py           # End-to-end integration tests
├── requirements.txt
├── pyproject.toml
└── .env.example
```

---

## GCP BigQuery Invoice Schema

```
Dataset: finance_data

Table: invoices
  invoice_id          STRING   REQUIRED  -- PK
  purchase_order_id   STRING   NULLABLE  -- FK → purchase_orders
  vendor_id           STRING   REQUIRED  -- FK → vendors
  vendor_name         STRING   REQUIRED
  contract_id         STRING   NULLABLE  -- FK → contracts
  subtotal            NUMERIC  REQUIRED
  tax_amount          NUMERIC  REQUIRED
  discount_applied    NUMERIC  REQUIRED
  total_amount        NUMERIC  REQUIRED
  currency            STRING   REQUIRED  -- ISO 4217
  invoice_date        DATE     REQUIRED
  service_period_start DATE    NULLABLE
  service_period_end   DATE    NULLABLE
  due_date            DATE     NULLABLE
  payment_date        DATE     NULLABLE
  created_at          TIMESTAMP REQUIRED

Table: invoice_line_items
  line_item_id     STRING   REQUIRED  -- PK
  invoice_id       STRING   REQUIRED  -- FK → invoices
  material_code    STRING   REQUIRED
  description      STRING   REQUIRED
  quantity         NUMERIC  REQUIRED
  unit_of_measure  STRING   REQUIRED
  unit_price       NUMERIC  REQUIRED
  line_total       NUMERIC  REQUIRED
  currency         STRING   REQUIRED
```

---

## Contract Types Supported

| Type | Example | Leakage Risk Clauses |
|---|---|---|
| `supplier` | Bulk Chemical Supply Agreement | Pricing tiers, rebates, payment terms, expiry |
| `customer` | Blasting Services Master Agreement | Volume tier pricing, quarterly rebates |
| `amendment` | CPI Price Review Amendment | Updated pricing must supersede original rates |
| `framework` | Framework services agreement | Term/expiry compliance |

---

## Quick Start

### Prerequisites

- Python 3.11+
- Azure AI Foundry project with an agent-capable model deployment (e.g. `gpt-4o`)
- Azure subscription (for production deployment)

### Installation

```bash
pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
# Edit .env with your Azure AI Foundry connection details
```

Key settings in `.env`:

```ini
# For Azure AI Foundry (production):
AZURE_AI_PROJECT_CONNECTION_STRING=<your-project-endpoint>
AZURE_AI_MODEL_DEPLOYMENT=gpt-4o

# Leave blank or set to true for mock/PoC mode (no Azure needed):
SHAREPOINT_MOCK_MODE=true
BIGQUERY_MOCK_MODE=true
```

### Run Locally (PoC / Mock Mode)

```bash
uvicorn src.main:app --reload --port 8000
```

Open the interactive API docs at: **http://localhost:8000/docs**

### Run Tests

```bash
python -m pytest tests/ -v
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Service health & mock-mode status |
| `GET` | `/schema/invoices` | BigQuery invoice dataset schema |
| `GET` | `/contracts` | List contracts (filters: `contract_type`, `vendor_id`) |
| `GET` | `/contracts/{id}` | Full contract details |
| `GET` | `/invoices` | List invoices (filters: `vendor_id`, `contract_id`, date range) |
| `POST` | `/analyse` | **Run full leakage analysis** |

### Example: Run Full Analysis

```bash
curl -X POST http://localhost:8000/analyse \
  -H "Content-Type: application/json" \
  -d '{}'
```

### Example: Analyse Specific Vendor

```bash
curl -X POST http://localhost:8000/analyse \
  -H "Content-Type: application/json" \
  -d '{"vendor_ids": ["SUP-001"], "period_start": "2024-01-01", "period_end": "2024-12-31"}'
```

### Example Response (truncated)

```json
{
  "analysis_id": "ANLYS-A1B2C3D4",
  "invoices_analysed": 5,
  "contracts_analysed": 4,
  "total_leakage_amount": 82560.00,
  "currency": "AUD",
  "critical_risk_count": 1,
  "high_risk_count": 2,
  "executive_summary": "Analysis completed. 5 invoice(s) reviewed across 4 contract(s). Total estimated leakage: AUD 82,560.00. 1 CRITICAL and 2 HIGH risk invoice(s) identified.",
  "invoice_risk_scores": [
    {
      "invoice_id": "INV-2024-00389",
      "vendor_name": "FastFreight Logistics Pty Ltd",
      "overall_risk_level": "critical",
      "risk_score": 40.0,
      "total_leakage_amount": 29600.0,
      "findings": [
        {
          "category": "expired_terms_applied",
          "risk_level": "critical",
          "description": "Invoice INV-2024-00389 references contract CTR-2022-018 which expired on 2024-06-30.",
          "recommendation": "Verify contract renewal status. Escalate to Procurement and Legal."
        }
      ]
    }
  ]
}
```

---

## PoC Success Criteria

| Criterion | Status |
|---|---|
| Detects pricing drift (wrong tier applied) | ✅ |
| Detects missed rebates (annual volume) | ✅ |
| Detects missed early payment discounts | ✅ |
| Detects expired contract terms applied | ✅ |
| Detects volume tier violations | ✅ |
| Returns risk scores (0–100) per invoice | ✅ |
| Returns explainable findings with contract evidence | ✅ |
| Returns remediation recommendations | ✅ |
| Integrates with Azure AI Foundry (multi-agent) | ✅ |
| Mock modes for SharePoint & BigQuery (PoC demo) | ✅ |
| REST API for integration | ✅ |

---

## Deploying to Azure AI Foundry

1. Create an Azure AI Foundry project and deploy a `gpt-4o` model.
2. Set `AZURE_AI_PROJECT_CONNECTION_STRING` to the project endpoint in your `.env`.
3. Set `SHAREPOINT_MOCK_MODE=false` and configure `SHAREPOINT_SITE_URL` for real SharePoint integration.
4. Set `BIGQUERY_MOCK_MODE=false` and configure `GCP_PROJECT_ID` / `GCP_CREDENTIALS_PATH` for real BigQuery.
5. Deploy the FastAPI app to Azure Container Apps or Azure App Service.

When `AZURE_AI_PROJECT_CONNECTION_STRING` is set, the `/analyse` endpoint creates all agents in Azure AI Foundry and runs the full multi-agent orchestration workflow.

---

## Security

- No credentials are stored in code; all secrets are loaded from environment variables.
- Mock mode is enabled by default — no external calls are made without explicit configuration.
- Agent tools use parameterised inputs — no SQL or query injection risk.
