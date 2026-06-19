# Story: Manual Quote Currency Conversion

**Epic:** Output Quality / Quotation Usability  
**Priority:** High (workshop export readiness — Middle East / international quoting)  
**Status:** Implemented ✓  
**Branch:** `v2-feature-review-engine`

---

## 1. User Story

> As a workshop owner quoting to a customer in a different currency,  
> I want to enter a manual exchange rate and see the customer quote price  
> alongside my internal costing price,  
> so that I can produce a single document showing both the internal cost and the customer-facing quote.

---

## 2. Files Changed

| File | Change |
|------|--------|
| `app.py` | (1) `init_session()` — 3 new session state keys; (2) `page_time_estimate()` — costing currency renamed, caption added, checkbox + quote currency block added, customer quote display block added, breakdown table gains optional quote column |

---

## 3. New Session State Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `est_show_quote_currency` | bool | `False` | Whether quote currency conversion is shown |
| `est_quote_currency` | str | `"USD ($)"` | Selected quote currency option |
| `est_exchange_rate` | float | `1.0` | Manual rate: how many costing-currency units equal 1 quote-currency unit |

---

## 4. Formula

```
quote_price_per_part = costing_price_per_part / exchange_rate
quote_batch_total    = costing_batch_total    / exchange_rate
```

Exchange rate direction: **1 [Quote Currency] = ? [Costing Currency]**

Example — Costing: INR, Quote: AED, rate = 23.0:
- Internal costing: ₹ 4,600 per part
- Customer quote: 4,600 / 23 = AED 200 per part

---

## 5. UI Elements Added

| Element | Description |
|---|---|
| `"Costing Currency"` label | Renamed from `"Currency"` |
| Caption below costing currency | "All input rates are assumed to be in the selected costing currency. Changing this does not auto-convert entered rates." |
| Checkbox `"Show customer quote in another currency"` | Toggles the quote currency section |
| `"Quote Currency"` selectbox | Same 6-option list as costing currency |
| Exchange rate number input | Label: `"Exchange rate: 1 [Quote] = ? [Costing]"` |
| Reference links | Xe Currency Converter + Wise Currency Converter (markdown links) |
| `"Customer Quote"` subheader + metrics | Sell price + batch total in quote currency |
| Conversion formula caption | Shows the exact arithmetic used |
| Third column in breakdown table | `Per Part ([quote_sym]) — customer quote` when conversion enabled |
| CSV download | Includes the quote column when conversion is active |

---

## 6. Definition of Done

- [x] "Currency" → "Costing Currency" label.
- [x] Caption: "All input rates are assumed to be in the selected costing currency."
- [x] Checkbox persisted in `est_show_quote_currency`.
- [x] Quote Currency selectbox persisted in `est_quote_currency`.
- [x] Exchange rate input with label `"Exchange rate: 1 [Quote] = ? [Costing]"`.
- [x] Xe and Wise reference links displayed as markdown hyperlinks.
- [x] No live API / no auto-fetch.
- [x] If quote == costing currency, conversion hidden with info message.
- [x] Customer quote metrics block (sell price + batch total) displayed when active.
- [x] Breakdown table gains quote column when conversion active.
- [x] CSV export includes quote column when conversion active.
- [x] Disclaimer preserved.
- [x] `python tests/run_feature_detection_regression.py` → 18 PASS, 0 FAIL, 0 MISSING, 0 ERROR.
- [ ] Manual test: INR costing → AED customer quote (perform before demo).
