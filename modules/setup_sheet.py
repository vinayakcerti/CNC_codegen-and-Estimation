"""
Generate a printable HTML setup sheet for the CNC job.
Designed to look like a professional shop-floor document.
"""
from datetime import datetime


def _esc(v):
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_mm(v):
    try:
        return f"{float(v):.1f}"
    except (TypeError, ValueError):
        return "0.0"


def generate_setup_sheet(operations, machine, material, stock, features, time_result,
                          cost_result=None, job_name="CNC Job", notes=None):
    now = datetime.now().strftime("%Y-%m-%d  %H:%M")

    machine_name = machine.get("machine_name", "—")
    controller = machine.get("controller", "—")
    mat_name = material.get("name", "—")

    stock_l = stock.get("length", 0)
    stock_w = stock.get("width", 0)
    stock_h = stock.get("height", 0)
    stock_vol = stock.get("stock_volume", 0)
    part_vol = stock.get("part_volume", 0)
    removal_pct = ((stock_vol - part_vol) / stock_vol * 100) if stock_vol > 0 else 0

    total_min = time_result.get("total_machine_time_min", 0)
    cutting_min = time_result.get("cutting_time_min", 0)
    setup_min = time_result.get("setup_time_min", 0)
    effort = time_result.get("effort_label", "—")
    num_ops = time_result.get("num_operations", len(operations))
    num_tc = time_result.get("num_tool_changes", 0)

    # Deduplicate tools used
    seen = {}
    for op in operations:
        tn = op["tool_number"]
        if tn not in seen:
            seen[tn] = op
    tools_used = sorted(seen.values(), key=lambda o: o["tool_number"])

    # Build tool table rows
    tool_rows = ""
    for t in tools_used:
        tool_rows += f"""
        <tr>
          <td>T{t['tool_number']:02d}</td>
          <td>{_esc(t['tool_name'])}</td>
          <td>{t['spindle_rpm']} RPM</td>
          <td>{t['feed_rate_mm_min']} mm/min</td>
          <td>{_esc(t.get('notes', ''))}</td>
        </tr>"""

    # Build operation table rows
    op_rows = ""
    for op in operations:
        op_rows += f"""
        <tr>
          <td>{op['op_num']:02d}</td>
          <td>{_esc(op['feature_name'])}</td>
          <td>{_esc(op['feature_type'])}</td>
          <td>{_esc(op.get('setup_label', 'Unknown'))}</td>
          <td>{_esc(op['operation_type'])}</td>
          <td>{_fmt_mm(op.get('_x_pos'))}</td>
          <td>{_fmt_mm(op.get('_y_pos'))}</td>
          <td>{_fmt_mm(op.get('_length'))}</td>
          <td>{_fmt_mm(op.get('_width'))}</td>
          <td>{_fmt_mm(op.get('_depth'))}</td>
          <td>T{op['tool_number']:02d} — {_esc(op['tool_name'])}</td>
          <td>{op['spindle_rpm']}</td>
          <td>{op['feed_rate_mm_min']}</td>
          <td>{op['est_path_length_mm']}</td>
          <td>{_esc(op.get('notes', ''))}</td>
        </tr>"""

    # Cost section (optional)
    cost_section = ""
    if cost_result:
        rows = ""
        for item, val in cost_result.items():
            rows += f"<tr><td>{_esc(item)}</td><td>${val:.2f}</td></tr>"
        cost_section = f"""
      <div class="section">
        <div class="section-title">5 &nbsp; Cost Estimate</div>
        <table>
          <thead><tr><th>Item</th><th>Amount</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>"""

    # Notes / Revision History section (optional)
    notes_section = ""
    if notes:
        type_icon = {
            "Observation": "&#128309;", "Change": "&#128993;", "Approval": "&#128994;",
            "Issue": "&#128308;", "Sign-off": "&#9989;", "Other": "&#9898;",
        }
        note_rows = ""
        for n in reversed(notes):
            icon = type_icon.get(n.get("note_type", "Other"), "&#9898;")
            note_rows += f"""
            <tr>
              <td>{_esc(n.get('timestamp', ''))}</td>
              <td>{_esc(n.get('stage', ''))}</td>
              <td>{icon} {_esc(n.get('note_type', ''))}</td>
              <td>{_esc(n.get('author', ''))}</td>
              <td>{_esc(n.get('note', ''))}</td>
            </tr>"""
        section_num = 6 if cost_result else 6
        notes_section = f"""
      <div class="section">
        <div class="section-title">{section_num} &nbsp; Revision History &amp; Notes</div>
        <table>
          <thead>
            <tr>
              <th>Timestamp</th><th>Stage</th><th>Type</th><th>Author</th><th>Note</th>
            </tr>
          </thead>
          <tbody>{note_rows}</tbody>
        </table>
      </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>CNC Setup Sheet — {_esc(job_name)}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 11pt;
    color: #1a1a1a;
    background: #fff;
    padding: 20mm 18mm;
  }}
  @page {{ size: A4 portrait; margin: 15mm; }}
  @media print {{
    body {{ padding: 0; }}
    .no-print {{ display: none; }}
  }}

  /* Header */
  .job-header {{
    display: grid;
    grid-template-columns: 1fr auto;
    border: 2px solid #1a1a1a;
    margin-bottom: 14px;
  }}
  .job-header-left {{
    padding: 10px 14px;
    border-right: 2px solid #1a1a1a;
  }}
  .job-header-left h1 {{
    font-size: 18pt;
    font-weight: 700;
    letter-spacing: 0.02em;
  }}
  .job-header-left .sub {{
    font-size: 9pt;
    color: #555;
    margin-top: 2px;
  }}
  .job-header-right {{
    padding: 10px 14px;
    min-width: 200px;
    font-size: 9.5pt;
  }}
  .job-header-right div {{ margin-bottom: 4px; }}
  .job-header-right span {{ font-weight: 600; }}

  /* Warning banner */
  .warning-banner {{
    background: #fff3cd;
    border: 1.5px solid #e6a817;
    color: #6d4c00;
    padding: 7px 12px;
    font-size: 9pt;
    font-weight: 600;
    margin-bottom: 14px;
    text-align: center;
    letter-spacing: 0.04em;
  }}

  /* Sections */
  .section {{ margin-bottom: 16px; }}
  .section-title {{
    background: #1a1a1a;
    color: #fff;
    font-weight: 700;
    font-size: 10pt;
    padding: 4px 10px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    margin-bottom: 6px;
  }}

  /* Metric grid */
  .metric-grid {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    margin-bottom: 0;
  }}
  .metric-box {{
    border: 1px solid #ccc;
    padding: 8px 10px;
  }}
  .metric-label {{
    font-size: 8pt;
    color: #666;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }}
  .metric-value {{
    font-size: 13pt;
    font-weight: 700;
    margin-top: 2px;
  }}

  /* Tables */
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 9.5pt;
  }}
  thead tr {{ background: #f0f0f0; }}
  th {{
    border: 1px solid #bbb;
    padding: 5px 7px;
    text-align: left;
    font-weight: 700;
    font-size: 8.5pt;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }}
  td {{
    border: 1px solid #ddd;
    padding: 4px 7px;
    vertical-align: top;
  }}
  tr:nth-child(even) td {{ background: #fafafa; }}

  /* Signature / sign-off */
  .signoff {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 20px;
    margin-top: 18px;
  }}
  .signoff-box {{
    border-top: 2px solid #1a1a1a;
    padding-top: 6px;
    font-size: 9pt;
  }}
  .signoff-label {{ color: #555; font-size: 8pt; text-transform: uppercase; }}

  /* Print button */
  .print-btn {{
    display: inline-block;
    background: #1a1a1a;
    color: #fff;
    padding: 10px 22px;
    font-size: 11pt;
    font-weight: 600;
    cursor: pointer;
    border: none;
    margin-bottom: 18px;
    letter-spacing: 0.04em;
  }}
  .print-btn:hover {{ background: #333; }}
</style>
</head>
<body>

<div class="no-print">
  <button class="print-btn" onclick="window.print()">&#128438; Print / Save as PDF</button>
</div>

<div class="warning-banner">
  &#9888; DRAFT CNC SETUP SHEET — VERIFY ALL VALUES IN CAM/SIMULATOR BEFORE RUNNING ON MACHINE &#9888;
</div>

<div class="job-header">
  <div class="job-header-left">
    <h1>{_esc(job_name)}</h1>
    <div class="sub">CNC Process Planner — Auto-Generated Setup Sheet</div>
  </div>
  <div class="job-header-right">
    <div>Date: <span>{now}</span></div>
    <div>Machine: <span>{_esc(machine_name)}</span></div>
    <div>Controller: <span>{_esc(controller)}</span></div>
    <div>Material: <span>{_esc(mat_name)}</span></div>
    <div>Stock: <span>{stock_l:.1f} × {stock_w:.1f} × {stock_h:.1f} mm</span></div>
  </div>
</div>

<!-- Section 1: Summary metrics -->
<div class="section">
  <div class="section-title">1 &nbsp; Job Summary</div>
  <div class="metric-grid">
    <div class="metric-box">
      <div class="metric-label">Total Machine Time</div>
      <div class="metric-value">{total_min:.0f} min</div>
    </div>
    <div class="metric-box">
      <div class="metric-label">Cutting Time</div>
      <div class="metric-value">{cutting_min:.0f} min</div>
    </div>
    <div class="metric-box">
      <div class="metric-label">Setup Time</div>
      <div class="metric-value">{setup_min:.0f} min</div>
    </div>
    <div class="metric-box">
      <div class="metric-label">Effort Level</div>
      <div class="metric-value">{_esc(effort)}</div>
    </div>
    <div class="metric-box">
      <div class="metric-label">Operations</div>
      <div class="metric-value">{num_ops}</div>
    </div>
    <div class="metric-box">
      <div class="metric-label">Tool Changes</div>
      <div class="metric-value">{num_tc}</div>
    </div>
    <div class="metric-box">
      <div class="metric-label">Stock Volume</div>
      <div class="metric-value">{stock_vol:.1f} cm³</div>
    </div>
    <div class="metric-box">
      <div class="metric-label">Material Removal</div>
      <div class="metric-value">{removal_pct:.1f}%</div>
    </div>
  </div>
</div>

<!-- Section 2: Stock & Material -->
<div class="section">
  <div class="section-title">2 &nbsp; Stock &amp; Material</div>
  <table>
    <thead>
      <tr>
        <th>Material</th><th>Density (g/cm³)</th>
        <th>Length (mm)</th><th>Width (mm)</th><th>Height (mm)</th>
        <th>Stock Vol (cm³)</th><th>Part Vol (cm³)</th><th>Removal</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>{_esc(mat_name)}</td>
        <td>{material.get('density', '—')}</td>
        <td>{stock_l:.2f}</td>
        <td>{stock_w:.2f}</td>
        <td>{stock_h:.2f}</td>
        <td>{stock_vol:.2f}</td>
        <td>{part_vol:.2f}</td>
        <td>{removal_pct:.1f}%</td>
      </tr>
    </tbody>
  </table>
</div>

<!-- Section 3: Tool List -->
<div class="section">
  <div class="section-title">3 &nbsp; Tool List</div>
  <table>
    <thead>
      <tr>
        <th>T#</th><th>Tool Name</th><th>Spindle</th><th>Feed Rate</th><th>Notes</th>
      </tr>
    </thead>
    <tbody>{tool_rows}</tbody>
  </table>
</div>

<!-- Section 4: Operation Sequence -->
<div class="section">
  <div class="section-title">4 &nbsp; Operation Sequence</div>
  <table>
    <thead>
      <tr>
        <th>#</th><th>Feature</th><th>Type</th><th>Setup</th><th>Operation</th>
        <th>X</th><th>Y</th><th>L</th><th>W</th><th>D</th>
        <th>Tool</th><th>RPM</th><th>Feed (mm/min)</th><th>Path (mm)</th><th>Notes</th>
      </tr>
    </thead>
    <tbody>{op_rows}</tbody>
  </table>
</div>

{cost_section}

{notes_section}

<!-- Sign-off -->
<div class="section">
  <div class="section-title">Sign-off</div>
  <div class="signoff">
    <div class="signoff-box">
      <div class="signoff-label">Prepared by</div>
      &nbsp;
    </div>
    <div class="signoff-box">
      <div class="signoff-label">Checked by</div>
      &nbsp;
    </div>
    <div class="signoff-box">
      <div class="signoff-label">Approved by</div>
      &nbsp;
    </div>
  </div>
</div>

</body>
</html>"""

    return html
