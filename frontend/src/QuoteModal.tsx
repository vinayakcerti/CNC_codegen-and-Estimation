import { useEffect, useState } from "react";
import type { ChangeEvent } from "react";
import { lsGet, lsSet } from "./storage";

// ---- Branded customer Quote generator (MVP-2) --------------------------------
// Client-side, localStorage-backed: company block + logo, a saved customer
// library, auto-incrementing quote numbers, and CONFIGURABLE currency + tax
// dropdowns (India GST, Gulf VAT, or a custom-named component you save and
// reuse) — so the same tool quotes for India and the Middle East. Generates a
// print-ready HTML quote (Save as PDF). Server-side storage/quotas are the
// separate multi-tenancy launch work.

export interface QuoteInput {
  partName: string;
  qty: number;
  unitAmount: number; // pre-tax customer price per unit (incl. margin)
}

interface Party {
  name: string;
  company: string;
  address: string;
  gstin: string;
  email: string;
  phone: string;
}
interface Company {
  name: string;
  address: string;
  logo: string; // data URL
}
interface TaxPreset { name: string; rate: number }
interface CurrencyPreset { code: string; symbol: string }

const BASE_CURRENCIES: CurrencyPreset[] = [
  { code: "INR", symbol: "₹" },
  { code: "USD", symbol: "$" },
  { code: "AED", symbol: "AED " },
  { code: "SAR", symbol: "SAR " },
  { code: "QAR", symbol: "QAR " },
  { code: "OMR", symbol: "OMR " },
  { code: "KWD", symbol: "KWD " },
  { code: "BHD", symbol: "BHD " },
  { code: "EUR", symbol: "€" },
  { code: "GBP", symbol: "£" },
];
const BASE_TAXES: TaxPreset[] = [
  { name: "No tax", rate: 0 },
  { name: "GST 18%", rate: 18 },
  { name: "GST 12%", rate: 12 },
  { name: "GST 28%", rate: 28 },
  { name: "VAT 5%", rate: 5 },
  { name: "VAT 15%", rate: 15 },
];
const TEMPLATES: { id: string; name: string; accent: string }[] = [
  { id: "blue", name: "Professional Blue", accent: "#2f6fb0" },
  { id: "slate", name: "Classic Slate", accent: "#334155" },
  { id: "teal", name: "Modern Teal", accent: "#0f766e" },
  { id: "maroon", name: "Elegant Maroon", accent: "#7a2e3a" },
  { id: "green", name: "Fresh Green", accent: "#2f7a44" },
];

function load<T>(key: string, fallback: T): T {
  try {
    const raw = lsGet(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}
const save = (key: string, v: unknown) => lsSet(key, JSON.stringify(v));

const money = (v: number, sym: string) =>
  sym + v.toLocaleString("en-US", { maximumFractionDigits: 2, minimumFractionDigits: 2 });

function openPrintDoc(html: string) {
  const w = window.open("", "_blank", "width=900,height=1000");
  if (!w) {
    alert("Please allow pop-ups to download the quote.");
    return;
  }
  w.document.open();
  w.document.write(html);
  w.document.close();
  w.focus();
  setTimeout(() => w.print(), 350);
}

function quoteHtml(o: {
  company: Company; customer: Party; quoteNo: string; date: string;
  part: string; qty: number; unit: number; sym: string;
  tax: TaxPreset; notes: string; accent: string;
}): string {
  const esc = (s: string) =>
    (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const sub = o.qty * o.unit;
  const taxAmt = sub * (o.tax.rate / 100);
  const total = sub + taxAmt;
  const logo = o.company.logo
    ? `<img src="${o.company.logo}" alt="logo" style="max-height:56px;max-width:190px;object-fit:contain">`
    : `<div style="font-size:20px;font-weight:700">${esc(o.company.name || "Your Company")}</div>`;
  const custLines = [o.customer.company || o.customer.name, o.customer.address,
    o.customer.gstin ? "GSTIN/TRN: " + o.customer.gstin : "",
    o.customer.email, o.customer.phone].filter(Boolean).map(esc).join("<br>");
  return `<!doctype html><html><head><meta charset="utf-8"><title>Quotation ${esc(o.quoteNo)}</title>
<style>
  :root{--ink:#1c2530;--mut:#5a6470;--line:#d5dae1;--band:#f5f7fa;--accent:${o.accent};}
  *{box-sizing:border-box}
  body{font:13px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;color:var(--ink);margin:0;padding:32px 36px}
  .top{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:2px solid var(--accent);padding-bottom:14px}
  .co .addr{color:var(--mut);font-size:12px;margin-top:4px;white-space:pre-line}
  .qbox{text-align:right}
  .qbox h1{margin:0;font-size:26px;letter-spacing:.04em;color:var(--accent)}
  .qbox .meta{color:var(--mut);font-size:12px;margin-top:6px}
  .parties{display:flex;gap:28px;margin:22px 0 10px}
  .parties .lbl{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);margin-bottom:4px}
  table{width:100%;border-collapse:collapse;margin-top:8px}
  th,td{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left}
  th{background:var(--band);font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:var(--mut)}
  td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
  .totals{width:300px;margin-left:auto;margin-top:6px}
  .totals td{border:none;padding:4px 10px}
  .totals .grand td{border-top:2px solid var(--ink);font-weight:700;font-size:15px;padding-top:8px}
  .terms{margin-top:26px;color:var(--mut);font-size:11.5px;white-space:pre-line}
  .foot{margin-top:30px;border-top:1px solid var(--line);padding-top:10px;display:flex;justify-content:space-between;align-items:center;color:var(--mut);font-size:11px}
  @media print{body{padding:0 6px}}
</style></head><body>
<div class="top">
  <div class="co">${logo}<div class="addr">${esc(o.company.address)}</div></div>
  <div class="qbox"><h1>QUOTATION</h1><div class="meta"># ${esc(o.quoteNo)}<br>${esc(o.date)}</div></div>
</div>
<div class="parties">
  <div><div class="lbl">Bill to</div>${custLines || "&mdash;"}</div>
</div>
<table>
  <thead><tr><th>Description</th><th class="n">Qty</th><th class="n">Unit price</th><th class="n">Amount</th></tr></thead>
  <tbody>
    <tr><td>CNC machining — ${esc(o.part)}</td><td class="n">${o.qty}</td><td class="n">${money(o.unit, o.sym)}</td><td class="n">${money(sub, o.sym)}</td></tr>
  </tbody>
</table>
<table class="totals">
  <tr><td>Subtotal</td><td class="n">${money(sub, o.sym)}</td></tr>
  ${o.tax.rate > 0 ? `<tr><td>${esc(o.tax.name)}</td><td class="n">${money(taxAmt, o.sym)}</td></tr>` : ""}
  <tr class="grand"><td>Total</td><td class="n">${money(total, o.sym)}</td></tr>
</table>
${o.notes ? `<div class="terms"><b>Terms</b>\n${esc(o.notes)}</div>` : ""}
<div class="foot"><span>${esc(o.company.name)}</span><span>${o.company.logo ? "" : ""}Generated by CNC Plan &amp; Process Pro</span></div>
</body></html>`;
}

export function QuoteModal({
  open,
  onClose,
  quote,
}: {
  open: boolean;
  onClose: () => void;
  quote: QuoteInput;
}) {
  const [company, setCompany] = useState<Company>(() =>
    load("cnc.quote.company", { name: "", address: "", logo: "" }));
  const [customers, setCustomers] = useState<Party[]>(() =>
    load("cnc.quote.customers", [] as Party[]));
  const [customer, setCustomer] = useState<Party>({
    name: "", company: "", address: "", gstin: "", email: "", phone: "",
  });
  const [currencies, setCurrencies] = useState<CurrencyPreset[]>(() =>
    load("cnc.quote.currencies", BASE_CURRENCIES));
  const [curCode, setCurCode] = useState<string>(() => lsGet("cnc.quote.curCode") || "INR");
  const [taxes, setTaxes] = useState<TaxPreset[]>(() => load("cnc.quote.taxes", BASE_TAXES));
  const [taxName, setTaxName] = useState<string>(() => lsGet("cnc.quote.taxName") || "GST 18%");
  const [prefix, setPrefix] = useState<string>(() => lsGet("cnc.quote.prefix") || "QT");
  const [seq, setSeq] = useState<number>(() => Number(lsGet("cnc.quote.seq") || "1"));
  const [notes, setNotes] = useState<string>(() =>
    lsGet("cnc.quote.notes") ||
    "Prices valid 30 days. 50% advance, balance before dispatch. Delivery: 2–3 weeks ex-works.");
  const [templateId, setTemplateId] = useState<string>(() => lsGet("cnc.quote.template") || "blue");

  // Add-custom UI state
  const [newTaxName, setNewTaxName] = useState("");
  const [newTaxRate, setNewTaxRate] = useState("");
  const [newCurCode, setNewCurCode] = useState("");
  const [newCurSym, setNewCurSym] = useState("");

  useEffect(() => { if (open) setSeq(Number(lsGet("cnc.quote.seq") || "1")); }, [open]);
  if (!open) return null;

  const year = new Date().getFullYear();
  const quoteNo = `${prefix}-${year}-${String(seq).padStart(4, "0")}`;
  const cur = currencies.find((c) => c.code === curCode) || currencies[0];
  const tax = taxes.find((t) => t.name === taxName) || taxes[0];

  const persistCompany = (c: Company) => { setCompany(c); save("cnc.quote.company", c); };

  function onLogo(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    const r = new FileReader();
    r.onload = () => persistCompany({ ...company, logo: String(r.result) });
    r.readAsDataURL(f);
  }

  function pickCustomer(name: string) {
    const c = customers.find((x) => (x.company || x.name) === name);
    if (c) setCustomer(c);
  }
  function saveCustomer() {
    if (!customer.name && !customer.company) return;
    const key = customer.company || customer.name;
    const next = [...customers.filter((c) => (c.company || c.name) !== key), customer];
    setCustomers(next); save("cnc.quote.customers", next);
  }
  function addTax() {
    const rate = parseFloat(newTaxRate);
    if (!newTaxName.trim() || !Number.isFinite(rate)) return;
    const entry = { name: newTaxName.trim(), rate };
    const next = [...taxes.filter((t) => t.name !== entry.name), entry];
    setTaxes(next); save("cnc.quote.taxes", next);
    setTaxName(entry.name); lsSet("cnc.quote.taxName", entry.name);
    setNewTaxName(""); setNewTaxRate("");
  }
  function addCurrency() {
    const code = newCurCode.trim().toUpperCase();
    if (!code || !newCurSym.trim()) return;
    const entry = { code, symbol: newCurSym };
    const next = [...currencies.filter((c) => c.code !== code), entry];
    setCurrencies(next); save("cnc.quote.currencies", next);
    setCurCode(code); lsSet("cnc.quote.curCode", code);
    setNewCurCode(""); setNewCurSym("");
  }

  function generate() {
    persistCompany(company);
    saveCustomer();
    lsSet("cnc.quote.notes", notes);
    lsSet("cnc.quote.prefix", prefix);
    lsSet("cnc.quote.curCode", curCode);
    lsSet("cnc.quote.taxName", taxName);
    lsSet("cnc.quote.template", templateId);
    const accent = (TEMPLATES.find((t) => t.id === templateId) || TEMPLATES[0]).accent;
    openPrintDoc(quoteHtml({
      company, customer, quoteNo,
      date: new Date().toLocaleDateString("en-GB", { year: "numeric", month: "short", day: "numeric" }),
      part: quote.partName, qty: quote.qty, unit: quote.unitAmount,
      sym: cur.symbol, tax, notes, accent,
    }));
    const nextSeq = seq + 1;
    setSeq(nextSeq); lsSet("cnc.quote.seq", String(nextSeq)); // auto-number next
  }

  return (
    <div className="qm-backdrop" onClick={onClose}>
      <div className="qm" onClick={(e) => e.stopPropagation()}>
        <div className="qm-head">
          <span>Prepare Quote — <b>{quoteNo}</b></span>
          <button className="qm-x" onClick={onClose}>✕</button>
        </div>
        <div className="qm-body">
          <div className="qm-col">
            <div className="qm-sect">Your company</div>
            <input className="qm-in" placeholder="Company name" value={company.name}
              onChange={(e) => persistCompany({ ...company, name: e.target.value })} />
            <textarea className="qm-in" rows={2} placeholder="Address" value={company.address}
              onChange={(e) => persistCompany({ ...company, address: e.target.value })} />
            <label className="qm-logo">
              {company.logo ? <img src={company.logo} alt="logo" /> : "Upload logo (header + footer)"}
              <input type="file" accept="image/*" onChange={onLogo} hidden />
            </label>

            <div className="qm-sect">Bill to</div>
            {customers.length > 0 && (
              <select className="qm-in" defaultValue="" onChange={(e) => pickCustomer(e.target.value)}>
                <option value="">— saved customers —</option>
                {customers.map((c, i) => (
                  <option key={i} value={c.company || c.name}>{c.company || c.name}</option>
                ))}
              </select>
            )}
            <input className="qm-in" placeholder="Customer / company" value={customer.company}
              onChange={(e) => setCustomer({ ...customer, company: e.target.value })} />
            <input className="qm-in" placeholder="Contact name" value={customer.name}
              onChange={(e) => setCustomer({ ...customer, name: e.target.value })} />
            <textarea className="qm-in" rows={2} placeholder="Address" value={customer.address}
              onChange={(e) => setCustomer({ ...customer, address: e.target.value })} />
            <input className="qm-in" placeholder="GSTIN / TRN (tax id)" value={customer.gstin}
              onChange={(e) => setCustomer({ ...customer, gstin: e.target.value })} />
            <div className="qm-row2">
              <input className="qm-in" placeholder="Email" value={customer.email}
                onChange={(e) => setCustomer({ ...customer, email: e.target.value })} />
              <input className="qm-in" placeholder="Phone" value={customer.phone}
                onChange={(e) => setCustomer({ ...customer, phone: e.target.value })} />
            </div>
            <button className="qm-mini" onClick={saveCustomer}>+ Save customer</button>
          </div>

          <div className="qm-col">
            <div className="qm-sect">Template</div>
            <select className="qm-in" value={templateId}
              onChange={(e) => { setTemplateId(e.target.value); lsSet("cnc.quote.template", e.target.value); }}>
              {TEMPLATES.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>

            <div className="qm-sect">Quote number</div>
            <div className="qm-row2">
              <input className="qm-in" placeholder="Prefix" value={prefix}
                onChange={(e) => { setPrefix(e.target.value); lsSet("cnc.quote.prefix", e.target.value); }} />
              <input className="qm-in" value={quoteNo} readOnly title="Auto-increments after each quote" />
            </div>

            <div className="qm-sect">Currency</div>
            <select className="qm-in" value={curCode}
              onChange={(e) => { setCurCode(e.target.value); lsSet("cnc.quote.curCode", e.target.value); }}>
              {currencies.map((c) => (
                <option key={c.code} value={c.code}>{c.code} ({c.symbol.trim()})</option>
              ))}
            </select>
            <div className="qm-row2">
              <input className="qm-in" placeholder="Add code (e.g. QAR)" value={newCurCode}
                onChange={(e) => setNewCurCode(e.target.value)} />
              <input className="qm-in" placeholder="Symbol" value={newCurSym}
                onChange={(e) => setNewCurSym(e.target.value)} />
            </div>
            <button className="qm-mini" onClick={addCurrency}>+ Add &amp; save currency</button>

            <div className="qm-sect">Tax component</div>
            <select className="qm-in" value={taxName}
              onChange={(e) => { setTaxName(e.target.value); lsSet("cnc.quote.taxName", e.target.value); }}>
              {taxes.map((t) => (
                <option key={t.name} value={t.name}>{t.name}{t.rate > 0 ? ` — ${t.rate}%` : ""}</option>
              ))}
            </select>
            <div className="qm-row2">
              <input className="qm-in" placeholder="Name (e.g. VAT)" value={newTaxName}
                onChange={(e) => setNewTaxName(e.target.value)} />
              <input className="qm-in" type="number" placeholder="Rate %" value={newTaxRate}
                onChange={(e) => setNewTaxRate(e.target.value)} />
            </div>
            <button className="qm-mini" onClick={addTax}>+ Add &amp; save tax</button>

            <div className="qm-sect">Terms</div>
            <textarea className="qm-in" rows={3} value={notes}
              onChange={(e) => setNotes(e.target.value)} />
          </div>
        </div>
        <div className="qm-foot">
          <span className="qm-note">Amounts use your entered rates — quote in the currency you priced in. Saved locally in this browser.</span>
          <div>
            <button className="qm-mini" onClick={onClose}>Cancel</button>
            <button className="btn primary" onClick={generate}>Generate Quote (PDF)</button>
          </div>
        </div>
      </div>
    </div>
  );
}
