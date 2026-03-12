"""Mock sample data for the Contract Leakage POC.

Provides realistic representative contracts and invoices without exposing
real Orica data.  All monetary values, dates and identifiers are fictional.
"""

from datetime import date

from src.models.schemas import (
    Contract,
    ContractClause,
    ContractType,
    Invoice,
    InvoiceLineItem,
    PricingTier,
    RebateStructure,
)

# ---------------------------------------------------------------------------
# Sample Contracts (as if retrieved from SharePoint)
# ---------------------------------------------------------------------------

SAMPLE_CONTRACTS: list[Contract] = [
    # ------------------------------------------------------------------
    # Contract 1 – Supplier: Bulk Chemicals (active)
    # ------------------------------------------------------------------
    Contract(
        contract_id="CTR-2023-001",
        contract_type=ContractType.SUPPLIER,
        supplier_or_customer_id="SUP-001",
        supplier_or_customer_name="Apex Chemical Supplies Pty Ltd",
        contract_name="Bulk Ammonium Nitrate Supply Agreement 2023",
        effective_date=date(2023, 1, 1),
        expiry_date=date(2025, 12, 31),
        currency="AUD",
        pricing_tiers=[
            PricingTier(min_volume=0, max_volume=500, unit_price=450.00, currency="AUD"),
            PricingTier(min_volume=500, max_volume=2000, unit_price=420.00, currency="AUD"),
            PricingTier(min_volume=2000, max_volume=None, unit_price=390.00, currency="AUD"),
        ],
        rebates=[
            RebateStructure(
                rebate_type="annual_volume_rebate",
                threshold=5_000_000.00,
                rebate_percentage=2.5,
                calculation_period="annual",
            ),
            RebateStructure(
                rebate_type="early_payment_discount",
                threshold=0,
                rebate_percentage=1.0,
                calculation_period="monthly",
            ),
        ],
        clauses=[
            ContractClause(
                clause_type="pricing",
                description="Unit price is AUD 450/MT for volumes below 500 MT, "
                "AUD 420/MT for 500–2000 MT, AUD 390/MT for volumes exceeding 2000 MT per order.",
                effective_date=date(2023, 1, 1),
                expiry_date=date(2025, 12, 31),
                value={"price_review_mechanism": "CPI-linked annual review"},
            ),
            ContractClause(
                clause_type="rebate",
                description="2.5% annual volume rebate payable when cumulative annual "
                "spend exceeds AUD 5,000,000. Credit note to be issued within 30 days of year-end.",
                effective_date=date(2023, 1, 1),
                expiry_date=date(2025, 12, 31),
                value={"rebate_cap": "none"},
            ),
            ContractClause(
                clause_type="payment_terms",
                description="Net 30 days from invoice date. 1% early payment discount "
                "if settled within 10 days.",
                effective_date=date(2023, 1, 1),
                expiry_date=date(2025, 12, 31),
                value={"payment_currency": "AUD"},
            ),
        ],
        sharepoint_url="https://contoso.sharepoint.com/sites/contracts/Shared%20Documents/CTR-2023-001.pdf",
        raw_text_excerpt=(
            "SECTION 4 – PRICING: The Supplier shall invoice at the volume-tiered rates "
            "set out in Schedule A. Pricing tiers reset on the first day of each calendar month."
        ),
    ),
    # ------------------------------------------------------------------
    # Contract 2 – Supplier: Logistics (expired – key leakage scenario)
    # ------------------------------------------------------------------
    Contract(
        contract_id="CTR-2022-018",
        contract_type=ContractType.SUPPLIER,
        supplier_or_customer_id="SUP-002",
        supplier_or_customer_name="FastFreight Logistics Pty Ltd",
        contract_name="Explosives Transport & Logistics Services 2022",
        effective_date=date(2022, 7, 1),
        expiry_date=date(2024, 6, 30),  # Expired – invoices post this date use wrong rates
        currency="AUD",
        pricing_tiers=[
            PricingTier(min_volume=0, max_volume=None, unit_price=1_850.00, currency="AUD"),
        ],
        rebates=[],
        clauses=[
            ContractClause(
                clause_type="pricing",
                description="Fixed rate of AUD 1,850 per delivery run (up to 5 MT). "
                "Rate subject to renegotiation upon contract renewal.",
                effective_date=date(2022, 7, 1),
                expiry_date=date(2024, 6, 30),
                value={"rate_type": "fixed_per_run"},
            ),
            ContractClause(
                clause_type="expiry",
                description="Contract expires 30 June 2024. All deliveries after expiry "
                "must be governed by a new or renewed agreement.",
                effective_date=date(2022, 7, 1),
                expiry_date=date(2024, 6, 30),
                value={"auto_renewal": False},
            ),
        ],
        sharepoint_url="https://contoso.sharepoint.com/sites/contracts/Shared%20Documents/CTR-2022-018.pdf",
        raw_text_excerpt=(
            "SECTION 2 – TERM: This agreement commences 1 July 2022 and expires "
            "30 June 2024 unless terminated earlier or renewed in writing."
        ),
    ),
    # ------------------------------------------------------------------
    # Contract 3 – Customer: Mining services (active, tiered rebate)
    # ------------------------------------------------------------------
    Contract(
        contract_id="CTR-2024-005",
        contract_type=ContractType.CUSTOMER,
        supplier_or_customer_id="CUST-042",
        supplier_or_customer_name="Northstar Mining Operations Ltd",
        contract_name="Blasting Services Master Agreement 2024",
        effective_date=date(2024, 1, 1),
        expiry_date=date(2026, 12, 31),
        currency="AUD",
        pricing_tiers=[
            PricingTier(min_volume=0, max_volume=1000, unit_price=280.00, currency="AUD"),
            PricingTier(min_volume=1000, max_volume=5000, unit_price=255.00, currency="AUD"),
            PricingTier(min_volume=5000, max_volume=None, unit_price=230.00, currency="AUD"),
        ],
        rebates=[
            RebateStructure(
                rebate_type="quarterly_volume_rebate",
                threshold=2_000_000.00,
                rebate_percentage=1.5,
                calculation_period="quarterly",
            ),
        ],
        clauses=[
            ContractClause(
                clause_type="volume_tier",
                description="Pricing tiers apply per individual purchase order quantity. "
                "Orders may not be split to gain lower tier pricing.",
                effective_date=date(2024, 1, 1),
                expiry_date=date(2026, 12, 31),
                value={"tier_reset": "per_order"},
            ),
            ContractClause(
                clause_type="rebate",
                description="Customer receives 1.5% rebate on quarterly spend exceeding "
                "AUD 2,000,000. Rebate applied as credit against next quarter's invoices.",
                effective_date=date(2024, 1, 1),
                expiry_date=date(2026, 12, 31),
                value={"rebate_type": "credit_note"},
            ),
        ],
        sharepoint_url="https://contoso.sharepoint.com/sites/contracts/Shared%20Documents/CTR-2024-005.pdf",
        raw_text_excerpt=(
            "SCHEDULE B – PRICING MATRIX: Pricing is volume-tiered on a per-order basis. "
            "The applicable tier is determined by total order quantity as stated on the Purchase Order."
        ),
    ),
    # ------------------------------------------------------------------
    # Contract 4 – Amendment to CTR-2023-001 (updated pricing)
    # ------------------------------------------------------------------
    Contract(
        contract_id="CTR-2024-001A",
        contract_type=ContractType.AMENDMENT,
        supplier_or_customer_id="SUP-001",
        supplier_or_customer_name="Apex Chemical Supplies Pty Ltd",
        contract_name="Amendment 1 to CTR-2023-001 – CPI Price Review",
        effective_date=date(2024, 1, 1),
        expiry_date=date(2025, 12, 31),
        currency="AUD",
        pricing_tiers=[
            PricingTier(min_volume=0, max_volume=500, unit_price=462.00, currency="AUD"),
            PricingTier(min_volume=500, max_volume=2000, unit_price=430.00, currency="AUD"),
            PricingTier(min_volume=2000, max_volume=None, unit_price=399.00, currency="AUD"),
        ],
        rebates=[
            RebateStructure(
                rebate_type="annual_volume_rebate",
                threshold=5_000_000.00,
                rebate_percentage=2.5,
                calculation_period="annual",
            ),
            RebateStructure(
                rebate_type="early_payment_discount",
                threshold=0,
                rebate_percentage=1.0,
                calculation_period="monthly",
            ),
        ],
        clauses=[
            ContractClause(
                clause_type="pricing",
                description="Effective 1 January 2024, pricing is revised per CPI adjustment: "
                "AUD 462/MT (<500 MT), AUD 430/MT (500–2000 MT), AUD 399/MT (>2000 MT). "
                "All other terms of CTR-2023-001 remain unchanged.",
                effective_date=date(2024, 1, 1),
                expiry_date=date(2025, 12, 31),
                value={"amends_contract": "CTR-2023-001", "cpi_adjustment_rate": 2.67},
            ),
            ContractClause(
                clause_type="payment_terms",
                description="Net 30 days from invoice date. 1% early payment discount "
                "if settled within 10 days. (Carried forward from CTR-2023-001, clause unchanged.)",
                effective_date=date(2024, 1, 1),
                expiry_date=date(2025, 12, 31),
                value={"payment_currency": "AUD"},
            ),
        ],
        sharepoint_url="https://contoso.sharepoint.com/sites/contracts/Shared%20Documents/CTR-2024-001A.pdf",
        raw_text_excerpt=(
            "AMENDMENT 1: Clause 4.1 (Pricing) of the Agreement dated 1 January 2023 "
            "is hereby amended to reflect the CPI adjustment effective 1 January 2024."
        ),
    ),
]

# ---------------------------------------------------------------------------
# Sample Invoices (as if retrieved from BigQuery)
# ---------------------------------------------------------------------------

SAMPLE_INVOICES: list[Invoice] = [
    # ------------------------------------------------------------------
    # Invoice 1 – SUP-001, correct pricing (no leakage)
    # ------------------------------------------------------------------
    Invoice(
        invoice_id="INV-2024-00101",
        purchase_order_id="PO-2024-0450",
        vendor_id="SUP-001",
        vendor_name="Apex Chemical Supplies Pty Ltd",
        contract_id="CTR-2023-001",
        subtotal=819_000.00,
        tax_amount=81_900.00,
        discount_applied=0.00,
        total_amount=900_900.00,
        currency="AUD",
        invoice_date=date(2024, 3, 15),
        service_period_start=date(2024, 3, 1),
        service_period_end=date(2024, 3, 31),
        due_date=date(2024, 4, 14),
        line_items=[
            InvoiceLineItem(
                line_item_id="LI-001",
                material_code="AN-BULK-HDP",
                description="Ammonium Nitrate Bulk – Heavy Density Prill",
                quantity=1_950.0,
                unit_of_measure="MT",
                unit_price=420.00,  # Correct: 500-2000 MT tier
                line_total=819_000.00,
                currency="AUD",
            ),
        ],
    ),
    # ------------------------------------------------------------------
    # Invoice 2 – SUP-001, pricing drift: old rate used instead of
    # post-amendment rate (CTR-2024-001A applies from 2024-01-01)
    # ------------------------------------------------------------------
    Invoice(
        invoice_id="INV-2024-00215",
        purchase_order_id="PO-2024-0512",
        vendor_id="SUP-001",
        vendor_name="Apex Chemical Supplies Pty Ltd",
        contract_id="CTR-2023-001",
        subtotal=840_000.00,
        tax_amount=84_000.00,
        discount_applied=0.00,
        total_amount=924_000.00,
        currency="AUD",
        invoice_date=date(2024, 6, 10),
        service_period_start=date(2024, 6, 1),
        service_period_end=date(2024, 6, 30),
        due_date=date(2024, 7, 10),
        line_items=[
            InvoiceLineItem(
                line_item_id="LI-001",
                material_code="AN-BULK-HDP",
                description="Ammonium Nitrate Bulk – Heavy Density Prill",
                quantity=2_000.0,
                unit_of_measure="MT",
                unit_price=420.00,  # INCORRECT: Amendment CTR-2024-001A sets AUD 430/MT for this tier
                line_total=840_000.00,
                currency="AUD",
            ),
        ],
    ),
    # ------------------------------------------------------------------
    # Invoice 3 – SUP-002, expired contract terms applied
    # Contract expired 2024-06-30, invoice dated 2024-08-15
    # ------------------------------------------------------------------
    Invoice(
        invoice_id="INV-2024-00389",
        purchase_order_id="PO-2024-0601",
        vendor_id="SUP-002",
        vendor_name="FastFreight Logistics Pty Ltd",
        contract_id="CTR-2022-018",
        subtotal=29_600.00,
        tax_amount=2_960.00,
        discount_applied=0.00,
        total_amount=32_560.00,
        currency="AUD",
        invoice_date=date(2024, 8, 15),  # AFTER contract expiry
        service_period_start=date(2024, 8, 1),
        service_period_end=date(2024, 8, 31),
        due_date=date(2024, 9, 14),
        line_items=[
            InvoiceLineItem(
                line_item_id="LI-001",
                material_code="TRANS-EXPL-RUN",
                description="Explosives Transport – Delivery Run",
                quantity=16.0,
                unit_of_measure="run",
                unit_price=1_850.00,  # Expired contract rate – no valid agreement
                line_total=29_600.00,
                currency="AUD",
            ),
        ],
    ),
    # ------------------------------------------------------------------
    # Invoice 4 – CUST-042, wrong pricing tier applied (split order leakage)
    # Customer ordered 3200 MT (tier 2: AUD 255) but invoiced at tier 1 rate
    # ------------------------------------------------------------------
    Invoice(
        invoice_id="INV-2024-00442",
        purchase_order_id="PO-2024-0733",
        vendor_id="CUST-042",
        vendor_name="Northstar Mining Operations Ltd",
        contract_id="CTR-2024-005",
        subtotal=896_000.00,
        tax_amount=89_600.00,
        discount_applied=0.00,
        total_amount=985_600.00,
        currency="AUD",
        invoice_date=date(2024, 9, 20),
        service_period_start=date(2024, 9, 1),
        service_period_end=date(2024, 9, 30),
        due_date=date(2024, 10, 20),
        line_items=[
            InvoiceLineItem(
                line_item_id="LI-001",
                material_code="BLT-EMUL-BULK",
                description="Bulk Emulsion Explosives",
                quantity=3_200.0,
                unit_of_measure="MT",
                unit_price=280.00,  # INCORRECT: 3200 MT falls in 1000-5000 tier → AUD 255/MT
                line_total=896_000.00,
                currency="AUD",
            ),
        ],
    ),
    # ------------------------------------------------------------------
    # Invoice 5 – SUP-001, missed rebate scenario
    # Annual spend with SUP-001 in 2023 exceeded AUD 5M threshold
    # but no rebate credit note was applied
    # ------------------------------------------------------------------
    Invoice(
        invoice_id="INV-2024-00501",
        purchase_order_id="PO-2024-0800",
        vendor_id="SUP-001",
        vendor_name="Apex Chemical Supplies Pty Ltd",
        contract_id="CTR-2023-001",
        subtotal=546_000.00,
        tax_amount=54_600.00,
        discount_applied=0.00,  # MISSING: 1% early payment discount (paid within 10 days)
        total_amount=600_600.00,
        currency="AUD",
        invoice_date=date(2024, 11, 5),
        service_period_start=date(2024, 11, 1),
        service_period_end=date(2024, 11, 30),
        due_date=date(2024, 12, 5),
        payment_date=date(2024, 11, 12),  # Paid within 10 days – 1% discount earned but not taken
        line_items=[
            InvoiceLineItem(
                line_item_id="LI-001",
                material_code="AN-BULK-HDP",
                description="Ammonium Nitrate Bulk – Heavy Density Prill",
                quantity=1_300.0,
                unit_of_measure="MT",
                unit_price=420.00,
                line_total=546_000.00,
                currency="AUD",
            ),
        ],
    ),
]
