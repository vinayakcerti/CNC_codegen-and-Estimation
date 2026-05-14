# Story: VMC Estimation, Pricing, Currency, and Tolerance Configuration

**Epic:** Output Quality / Operator Usability  
**Priority:** High (quoting readiness for real workshops)  
**Status:** Implemented ✓  
**Branch:** `v2-feature-review-engine`

---

## 1. User Story

> As a VMC workshop owner or quotation engineer,  
> I want to enter my workshop's real hourly rates, setup costs, and tolerance requirements  
> in my local currency and get a fully itemised cost estimate,  
> so that I can use the app to produce a realistic first-pass quotation.

---

## 2. Files Changed

| File | Change |
|------|--------|
| `app.py` | (1) `init_session()` — 11 new `est_*` session state keys added; (2) `page_time_estimate()` — old single-currency "Job Cost Estimator" replaced with new multi-currency, tolerance-aware "Quote Configuration + Quotation Estimate" section |

`modules/time_estimator.py` — **not changed.** Time calculation logic is unchanged.

---

## 3. Session State Keys Added (persisted across page navigation)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `est_currency` | str | `"INR (₹)"` | Selected currency option |
| `est_machine_rate` | float | `800.0` | Machine hourly rate in selected currency |
| `est_operator_rate` | float | `200.0` | Operator hourly rate |
| `est_setup_cost` | float | `500.0` | Setup fixed cost per batch (flat fee) |
| `est_tool_cost` | float | `300.0` | Tool wear / consumable cost per batch |
| `est_material_price_kg` | float | `80.0` | Material price per kg |
| `est_material_waste_pct` | float | `15.0` | Material waste / offcut % |
| `est_batch_qty` | int | `1` | Number of parts in the batch |
| `est_margin_pct` | float | `20.0` | Profit margin % |
| `est_tolerance` | str | `"General (±0.20 mm) — ×1.00"` | Tolerance level selection |
| `est_complexity` | float | `1.0` | Complexity factor (1.0–2.0) |

---

## 4. Currencies Supported

| Option label | Symbol used in fields |
|---|---|
| INR (₹) | ₹ |
| USD ($) | $ |
| EUR (€) | € |
| AED | AED |
| OMR | OMR |
| SAR | SAR |

No live exchange conversion. All rates are entered in the selected currency.

---

## 5. Tolerance Multipliers

| Level | Tolerance | Multiplier |
|---|---|---|
| General | ±0.20 mm | ×1.00 |
| Medium | ±0.10 mm | ×1.15 |
| Tight | ±0.05 mm | ×1.35 |
| Very tight | ±0.02 mm | ×1.60 |

---

## 6. Estimate Formula

```
material_cost      = stock_weight_kg × material_price_kg × (1 + waste_pct/100)
machine_time_cost  = (cutting_time_min / 60) × machine_hourly_rate
operator_cost      = (operator_effort_min / 60) × operator_hourly_rate
setup_cost_part    = setup_fixed_cost / batch_qty
tool_cost_part     = tool_consumable_cost / batch_qty

subtotal_base      = material + machine_time + operator + setup/batch + tool/batch

tolerance_impact   = subtotal_base × (tolerance_multiplier − 1.0)
complexity_input   = (subtotal_base + tolerance_impact) × (complexity_factor − 1.0)
subtotal_adjusted  = subtotal_base + tolerance_impact + complexity_impact

margin_amount      = subtotal_adjusted × (margin_pct / 100)
price_per_part     = subtotal_adjusted + margin_amount
batch_total        = price_per_part × batch_qty
```

---

## 7. Breakdown Table Rows

1. Material (incl. waste)
2. Machine time
3. Operator
4. Setup fixed (÷ batch)
5. Tool / consumables (÷ batch)
6. Tolerance adjustment (label, ×multiplier)
7. Complexity adjustment (×factor)
8. Subtotal before margin
9. Profit margin (%)
10. Sell price per part

---

## 8. Definition of Done

- [x] Currency selector (6 currencies) with symbol used in all field labels.
- [x] 7 rate/config inputs with `key=` for session persistence.
- [x] Tolerance level selectbox (4 options with multipliers).
- [x] Complexity factor slider (1.0–2.0).
- [x] Full 10-row breakdown table displayed.
- [x] Batch total metric displayed.
- [x] Disclaimer: "This is a quotation/planning estimate. Final price should be reviewed by the workshop."
- [x] Download button for CSV export.
- [x] All inputs persist across page navigation via session state.
- [x] `python tests/run_feature_detection_regression.py` → 18 PASS, 0 FAIL, 0 MISSING, 0 ERROR.
- [ ] Manual test with M03_vmc_blind_rectangular_pocket.step (perform before demo).
