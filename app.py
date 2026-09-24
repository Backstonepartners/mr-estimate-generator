#!/usr/bin/env python3
from flask import Flask, render_template, request, send_file, jsonify
from werkzeug.utils import secure_filename
import os
import pathlib
import base64
import io
from datetime import datetime
import tempfile
import html as html_lib

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max
app.config['UPLOAD_FOLDER'] = '/tmp/estimate_uploads'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

BASE = pathlib.Path(__file__).resolve().parent

# M&R Brand Colors
NAVY = '#023880'
GREEN = '#6EA241'
CREAM = '#f9f7f4'
_logo_path = BASE / 'static' / 'logo-white.png'
LOGO = ('data:image/png;base64,' + base64.b64encode(_logo_path.read_bytes()).decode()) if _logo_path.exists() else ''

def html_escape(v):
    return html_lib.escape(str(v), quote=True)

def money2(v):
    return "$" + format(v, ",.2f")

def generate_estimate_pdf(data, images=None, extras=None):
    """Generate luxury architectural proposal PDF from form data"""

    client_name = html_escape(data.get('client_name', 'Client'))
    service_type = data.get('service_type', 'general')
    completion_time = data.get('completion_time', 'Estimated within 2-3 weeks')
    start_availability = data.get('start_availability', 'within 2 weeks of approval')
    zones = []

    # Parse zones
    zone_count = int(data.get('zone_count', 1))
    for i in range(zone_count):
        zone_name = data.get(f'zone_name_{i}', f'Area {i+1}')
        zone_area = float(data.get(f'zone_area_{i}', 0) or 0)
        zones.append((zone_name, zone_area))

    total_area = sum(a for _, a in zones)

    # Additional line items: flat amounts added on top of every option
    extras = [(desc, amt) for desc, amt in (extras or []) if desc or amt]
    extras_total = sum(amt for _, amt in extras)
    images = images or []

    # Parse pricing tiers (from form field names: tier1_rate, tier2_rate, tier3_rate)
    tier1_rate = float(data.get('tier1_rate', 7.50) or 7.50)
    tier2_rate = float(data.get('tier2_rate', 8.20) or 8.20)
    tier3_rate = float(data.get('tier3_rate', 9.00) or 9.00)
    base_amount = float(data.get('base_amount', 1600) or 1600)

    # Service-specific configuration
    service_config = {
        'turf': {
            'subtitle': 'Turf Installation Project',
            'investment_label': 'Complete Turf Installation',
            'option_names': ['Buffalo Pro', 'Emerald', 'Clover'],
            'inclusions': [
                ['Grass removal & excavation', 'Soil grading & compaction', 'Stone base preparation', 'Professional turf installation', 'Seaming & finishing', 'Infill application', 'Gravel distribution'],
                ['4-year labor guarantee', '15-year manufacturer warranty', 'Experienced crew (4 professionals)', '3-day completion timeframe', 'Full site cleanup', 'Walkways & pathways included']
            ]
        },
        'pavers': {
            'subtitle': 'Hardscape Installation Project',
            'investment_label': 'Complete Hardscape Installation',
            'option_names': ['Standard', 'Premium', 'Designer'],
            'inclusions': [
                ['Site excavation & prep', 'Base material installation', 'Sand bedding layer', 'Professional paver placement', 'Jointing & sealing', 'Edge finishing', 'Cleanup & restoration'],
                ['4-year labor guarantee', '10-year material warranty', 'Expert installation crew', '5-7 day completion', 'Full site restoration', 'Permeable options available']
            ]
        },
        'kitchen': {
            'subtitle': 'Outdoor Kitchen Installation',
            'investment_label': 'Complete Kitchen Installation',
            'option_names': ['Essential', 'Premium', 'Full Featured'],
            'inclusions': [
                ['Structure building & finishing', 'Appliance installation', 'Counter preparation', 'Electrical rough-in', 'Gas line prep', 'Drainage systems', 'Site finishing'],
                ['4-year labor guarantee', '5-year appliance coverage', 'Licensed & insured crew', '2-3 week completion', 'Full cleanup & testing', 'Performance guarantee']
            ]
        },
        'pergola': {
            'subtitle': 'Pergola Installation Project',
            'investment_label': 'Complete Pergola Installation',
            'option_names': ['Standard', 'Enhanced', 'Premium'],
            'inclusions': [
                ['Structural framing & support', 'Post & foundation work', 'Roof/shade installation', 'Finishing & stain/paint', 'Hardware & fasteners', 'Weather protection', 'Site preparation'],
                ['4-year labor guarantee', 'Weather protection guarantee', 'Licensed installation team', '1-2 week completion', 'Site cleanup included', 'Custom design included']
            ]
        },
        'lighting': {
            'subtitle': 'Outdoor Lighting Installation',
            'investment_label': 'Complete Lighting System',
            'option_names': ['Basic', 'Enhanced', 'Premium Smart'],
            'inclusions': [
                ['Fixture selection & design', 'Underground wiring', 'Transformer installation', 'Professional installation', 'Landscape integration', 'Testing & adjustment', 'Site restoration'],
                ['4-year labor guarantee', 'LED efficiency guarantee', 'Expert design consultation', '3-5 day installation', 'Full functionality testing', 'Smart controls available']
            ]
        },
        'general': {
            'subtitle': 'Landscape Installation Project',
            'investment_label': 'Complete Landscaping Project',
            'option_names': ['Classic', 'Premium', 'Elite'],
            'inclusions': [
                ['Site design & planning', 'Soil preparation', 'Planting & installation', 'Hardscape integration', 'Mulch & finishing', 'Irrigation setup', 'Site cleanup'],
                ['4-year labor guarantee', 'Plant health guarantee', 'Professional design team', 'Custom solutions', 'Full project cleanup', 'Maintenance guidance included']
            ]
        }
    }

    config = service_config.get(service_type, service_config['general'])
    option_names = config['option_names']

    grades = [
        (option_names[0], tier1_rate, False),
        (option_names[1], tier2_rate, True),  # Featured/Recommended
        (option_names[2], tier3_rate, False)
    ]

    # Calculate key figures using recommended (tier2) option
    recommended_total = (total_area * tier2_rate) + base_amount + extras_total
    deposit_amount = recommended_total * 0.5

    # Build pricing option cards
    option_cards = ""
    for option_name, rate, is_featured in grades:
        total = (total_area * rate) + base_amount + extras_total
        featured_class = "featured" if is_featured else ""
        recommended_badge = "<div class='option-recommended'>RECOMMENDED</div>" if is_featured else ""
        option_cards += f"""<div class='option-card {featured_class}'>
          <div class='option-name'>{option_name}</div>
          <div class='option-rate'>${rate:.2f} per sq ft</div>
          <div class='option-total'>{money2(total)}</div>
          {recommended_badge}
        </div>"""

    # Build zone summary for scope section (using recommended tier2)
    zone_summary = """<table class='scope-table'>
      <tr><th>Area</th><th class='num'>Size</th><th class='num'>Cost</th></tr>"""
    for zone_name, zone_area in zones:
        zone_summary += f"""<tr>
          <td class='scope-name'>{html_escape(zone_name)}</td>
          <td class='num scope-area'>{zone_area:,.0f} sq ft</td>
          <td class='num scope-price'>{money2(zone_area * tier2_rate)}</td>
        </tr>"""
    zone_summary += "</table>"

    extras_section = ""
    if extras:
        rows = "".join(f"""<tr>
          <td class='scope-name'>{html_escape(desc)}</td>
          <td class='num scope-price'>{money2(amt)}</td>
        </tr>""" for desc, amt in extras)
        extras_section = f"""<!-- ADDITIONAL ITEMS -->
<div class="section">
  <div class="section-title">Additional Items</div>
  <table class='scope-table'>
    <tr><th>Item</th><th class='num'>Cost</th></tr>
    {rows}
    <tr class='scope-total'><td>Additional items total</td><td class='num'>{money2(extras_total)}</td></tr>
  </table>
  <div class='extras-note'>Included in every option total above.</div>
</div>
"""

    # Build dynamic inclusions list from config
    inclusions_html = ""
    for col_idx, column_items in enumerate(config['inclusions']):
        title = 'Installation Services' if col_idx == 0 else 'Warranty & Support'
        items_list = ''.join([f'<li>{item}</li>' for item in column_items])
        inclusions_html += f"""<div class='inclusion-column'>
      <div class='inclusion-title'>{title}</div>
      <ul class='inclusion-list'>
        {items_list}
      </ul>
    </div>"""

    css = """
body{font-family:'Poppins','Segoe UI',Roboto,sans-serif;color:""" + NAVY + """;background:#fff}
.page{background:#fff;padding:.4in}

/* COVER PAGE */
.cover{background:linear-gradient(135deg, """ + NAVY + """ 0%, #0a1f3d 100%);padding:.55in;color:#fff;margin:-.4in -.4in .4in -.4in;position:relative;min-height:3.4in;display:flex;flex-direction:column;justify-content:space-between;box-shadow:inset 0 1px 0 rgba(255,255,255,.1)}
.cover-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:.2in}
.cover-logo{font-size:8pt;font-weight:700;letter-spacing:2pt;text-transform:uppercase;opacity:.85}
.cover-logo img{width:2.6in;height:auto;margin-bottom:.1in}
.cover-date{font-size:7pt;opacity:.6;text-transform:uppercase;letter-spacing:.3pt}
.cover-divider{height:1px;background:linear-gradient(90deg,rgba(255,255,255,0),rgba(255,255,255,.3),rgba(255,255,255,0));margin:.2in 0}
.cover-title{font-size:48pt;font-weight:900;line-height:1.05;margin:.15in 0 .05in 0;letter-spacing:-2pt;color:#fff}
.cover-subtitle{font-size:15pt;opacity:.95;margin-bottom:.35in;font-weight:300;letter-spacing:.8pt}
.cover-meta{display:grid;grid-template-columns:1fr 1fr;gap:.45in}
.meta-block{border-top:2px solid """ + GREEN + """;padding-top:.15in}
.meta-label{font-size:7.5pt;text-transform:uppercase;letter-spacing:.5pt;opacity:.65;margin-bottom:.08in;font-weight:600}
.meta-value{font-size:14pt;font-weight:700;color:#fff;letter-spacing:-.3pt}

/* INVESTMENT SECTION - HERO */
.investment-section{margin:.35in 0 .45in 0;padding:0}
.investment-hero{background:linear-gradient(135deg, #f5f7fa 0%, #eef1f5 100%);padding:.45in;border-left:6px solid """ + GREEN + """;display:grid;grid-template-columns:2.2fr 1.1fr;gap:.35in;align-items:stretch;border-radius:2px;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.investment-left{display:flex;flex-direction:column;justify-content:center}
.investment-label{font-size:8.5pt;text-transform:uppercase;letter-spacing:.4pt;color:""" + GREEN + """;margin-bottom:.08in;font-weight:700}
.investment-amount{font-size:52pt;font-weight:900;color:""" + NAVY + """;line-height:1;margin:.08in 0 .12in 0;letter-spacing:-1.5pt}
.investment-descriptor{font-size:9.5pt;color:#3c5a78;line-height:1.65;margin-top:.12in}
.investment-right{background:""" + NAVY + """;padding:.32in;border-radius:4px;color:#fff;text-align:center;display:flex;flex-direction:column;justify-content:center;min-height:1.35in;box-shadow:inset 0 1px 0 rgba(255,255,255,.1)}
.investment-right-label{font-size:7.5pt;text-transform:uppercase;letter-spacing:.4pt;opacity:.75;margin-bottom:.15in;font-weight:600}
.investment-right-text{font-size:32pt;font-weight:900;color:""" + GREEN + """;line-height:1;letter-spacing:-.5pt}

/* SECTION STYLING */
.section{margin:.4in 0;padding:0}
.section-title{font-size:14pt;font-weight:900;color:""" + NAVY + """;margin-bottom:.22in;text-transform:uppercase;letter-spacing:-.5pt;border-bottom:3px solid """ + GREEN + """;padding-bottom:.12in}

/* PRICING OPTIONS */
.option-cards{display:grid;grid-template-columns:repeat(3,1fr);gap:.28in;margin:.22in 0}
.option-card{background:#f9fafb;padding:.3in;border-radius:6px;border:1px solid #e8eef5;border-left:5px solid #c9d3de;position:relative;transition:all .2s;box-shadow:0 1px 3px rgba(0,0,0,.04)}
.option-card.featured{border:1px solid """ + GREEN + """;border-left:5px solid """ + GREEN + """;background:#f9fbf6;box-shadow:0 3px 12px rgba(110,162,65,.16)}
.option-card.featured .option-name{color:""" + GREEN + """;letter-spacing:-.3pt}
.option-card.featured .option-total{color:""" + GREEN + """;letter-spacing:-.5pt}
.option-name{font-size:11.5pt;font-weight:800;text-transform:uppercase;color:""" + NAVY + """;margin-bottom:.12in;letter-spacing:-.2pt}
.option-rate{font-size:9.5pt;color:#7a8899;margin-bottom:.14in;font-weight:600}
.option-total{font-size:24pt;font-weight:900;color:""" + NAVY + """;margin:.12in 0 0 0;line-height:1}
.option-recommended{font-size:6.5pt;text-transform:uppercase;color:""" + GREEN + """;font-weight:800;margin-top:.14in;display:inline-block;background:#f0f4e8;padding:.05in .1in;border-radius:3px;letter-spacing:.3pt}

/* ZONE BREAKDOWN */
.zone-breakdown{margin:.2in 0}
.zone-header{display:grid;grid-template-columns:2fr 1fr 1.2fr;gap:.2in;padding:.18in 0 .12in 0;border-bottom:2px solid """ + GREEN + """;margin-bottom:.12in}
.zone-header-item{font-size:8.5pt;font-weight:700;text-transform:uppercase;color:""" + GREEN + """;letter-spacing:.2pt}
.zone-header-item:nth-child(2),.zone-header-item:nth-child(3){text-align:right}
.zone-item{display:grid;grid-template-columns:2fr 1fr 1.2fr;gap:.2in;padding:.18in 0;border-bottom:1px solid #eef1f5;align-items:center}
.zone-item:last-child{border-bottom:none}
.zone-name{font-size:10.5pt;font-weight:600;color:""" + NAVY + """;letter-spacing:-.2pt}
.zone-area{font-size:9.5pt;color:#7a8899;text-align:right;font-weight:500}
.zone-price{font-size:11pt;font-weight:700;color:""" + GREEN + """;text-align:right;letter-spacing:-.3pt}

/* INCLUSIONS */
.inclusions-grid{display:grid;grid-template-columns:1fr 1fr;gap:.35in;margin:.22in 0}
.inclusion-column{padding-right:.12in}
.inclusion-title{font-size:9.5pt;font-weight:700;color:""" + GREEN + """;text-transform:uppercase;margin-bottom:.16in;letter-spacing:.3pt;border-bottom:2px solid """ + GREEN + """;padding-bottom:.1in}
.inclusion-list{margin:0;padding-left:.2in;line-height:1.75;font-size:9pt;color:#3c5a78}
.inclusion-list li{margin-bottom:.08in;font-weight:500}

/* TERMS GRID */
.terms-grid{display:grid;grid-template-columns:1fr 1fr;gap:.3in;margin:.22in 0}
.term-box{background:#f9fafb;padding:.22in;border-radius:6px;border:1px solid #e8eef5;border-left:4px solid #c9d3de;box-shadow:0 1px 3px rgba(0,0,0,.03)}
.term-box:nth-child(1),.term-box:nth-child(2){border-left:4px solid """ + GREEN + """}
.term-title{font-size:8.5pt;font-weight:700;color:""" + NAVY + """;margin-bottom:.1in;text-transform:uppercase;letter-spacing:.2pt}
.term-content{font-size:8.5pt;color:#3c5a78;line-height:1.6}

/* SIGNATURE */
.signature-section{margin-top:.4in;padding-top:.3in;border-top:2px solid #eef1f5}
.signature-line{display:grid;grid-template-columns:1fr 1fr;gap:.35in;margin-bottom:.25in}
.signature-item{font-size:8.5pt}
.signature-label{color:#7a8899;margin-bottom:.08in;text-transform:uppercase;letter-spacing:.2pt;font-size:7.5pt;font-weight:600}
.signature-name{font-weight:700;color:""" + NAVY + """;margin-top:.1in}
.signature-line-visual{border-bottom:1px solid """ + NAVY + """;margin:.1in 0;height:0}

/* PROJECT IMAGE HERO */
.project-image-page{page-break-before:always;page-break-after:always;padding-top:.1in}
.project-image-figure{text-align:center;margin:0 0 .25in 0;page-break-inside:avoid}
.project-image-figure img{max-width:100%;max-height:4.2in;border-radius:8px;border:1px solid #eef1f5}

/* SCOPE / LINE ITEM TABLES */
.scope-table{width:100%;border-collapse:collapse}
.scope-table th{font-size:8.5pt;font-weight:700;text-transform:uppercase;color:""" + GREEN + """;letter-spacing:.2pt;text-align:left;padding:.12in 0;border-bottom:2px solid """ + GREEN + """}
.scope-table td{padding:.14in 0;border-bottom:1px solid #eef1f5;vertical-align:top}
.scope-table .num{text-align:right}
.scope-name{font-weight:700;color:""" + NAVY + """;font-size:9.5pt}
.scope-area{color:#7a8899;font-size:9pt}
.scope-price{font-weight:700;color:""" + GREEN + """;font-size:9.5pt}
.scope-total td{font-weight:900;color:""" + NAVY + """;border-bottom:none;border-top:2px solid """ + NAVY + """}
.extras-note{font-size:8pt;color:#7a8899;margin-top:.1in;font-style:italic}
.image-caption{font-size:8.5pt;color:#7a8899;margin-top:.14in;text-align:center;font-style:italic;letter-spacing:.2pt}

/* FOOTER */
.footer{text-align:center;font-size:7.5pt;color:#7a8899;margin-top:.35in;padding-top:.2in;border-top:1px solid #eef1f5;letter-spacing:.3pt}

/* PAGE BREAK */
.page-break{page-break-after:always;margin:.3in 0}

/* PAGE MANAGEMENT */
.section{page-break-inside:avoid}
.option-cards{page-break-inside:avoid}
.zone-breakdown{page-break-inside:avoid}
.inclusions-grid{page-break-inside:avoid}
.terms-grid{page-break-inside:avoid}
.signature-section{page-break-inside:avoid}
"""

    image_section = ""
    if images:
        figures = "".join(f"""<div class="project-image-figure"><img src="{img}" alt="Project Rendering"></div>""" for img in images)
        image_section = f"""<!-- PROJECT RENDERINGS (own page) -->
<div class="project-image-page">
  <div class="section-title">Your Project Vision</div>
  {figures}
  <div class="image-caption">Your transformation awaits</div>
</div>
"""

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<style>{css}</style></head><body><div class="page">

<!-- COVER PAGE -->
<div class="cover">
  <div class="cover-header">
    <div class="cover-logo"><img src="{LOGO}" alt="M&R Outdoor Living"></div>
    <div class="cover-date">{datetime.now().strftime('%B %d, %Y')}</div>
  </div>
  <div class="cover-divider"></div>
  <div>
    <div class="cover-title">Project Estimate</div>
    <div class="cover-subtitle">{config['subtitle']}</div>
  </div>
  <div class="cover-meta">
    <div class="meta-block">
      <div class="meta-label">Client</div>
      <div class="meta-value">{client_name}</div>
    </div>
    <div class="meta-block">
      <div class="meta-label">Project Size</div>
      <div class="meta-value">{total_area:,.0f} sq ft</div>
    </div>
  </div>
</div>

<!-- INVESTMENT HERO SECTION -->
<div class="investment-section">
  <div class="investment-hero">
    <div class="investment-left">
      <div class="investment-label">{config['investment_label']}</div>
      <div class="investment-amount">{money2(recommended_total)}</div>
      <div class="investment-descriptor">Our recommended {option_names[1]} option with professional installation, expert craftsmanship, and complete project finishing. Includes comprehensive warranty coverage and full project completion guarantee.</div>
    </div>
    <div class="investment-right">
      <div class="investment-right-label">Deposit to Secure</div>
      <div class="investment-right-text">{money2(deposit_amount)}</div>
    </div>
  </div>
</div>

{image_section}

<!-- PRICING OPTIONS -->
<div class="section">
  <div class="section-title">Investment Options</div>
  <div class="option-cards">
    {option_cards}
  </div>
</div>

<!-- PROJECT SCOPE -->
<div class="section">
  <div class="section-title">Your Project Scope</div>
  <div class="zone-breakdown">
    {zone_summary}
  </div>
</div>

{extras_section}

<!-- WHAT'S INCLUDED -->
<div class="section">
  <div class="section-title">What's Included in This Estimate</div>
  <div class="inclusions-grid">
    {inclusions_html}
  </div>
</div>

<!-- PROJECT TERMS -->
<div class="section">
  <div class="section-title">Project Terms & Timeline</div>
  <div class="terms-grid">
    <div class="term-box">
      <div class="term-title">Estimate Validity</div>
      <div class="term-content">This estimate remains valid for 30 days from the date above.</div>
    </div>
    <div class="term-box">
      <div class="term-title">Payment Structure</div>
      <div class="term-content">50% deposit to secure your date. Remaining balance due upon completion.</div>
    </div>
    <div class="term-box">
      <div class="term-title">Project Timeline</div>
      <div class="term-content">Estimated build time: {completion_time}. Start availability: {start_availability}.</div>
    </div>
    <div class="term-box">
      <div class="term-title">Payment Methods</div>
      <div class="term-content">Credit card accepted. Processor fees added separately. Scope changes quoted separately.</div>
    </div>
  </div>
</div>

<!-- SIGNATURE & APPROVAL -->
<div class="signature-section">
  <div class="signature-line">
    <div class="signature-item">
      <div class="signature-label">Client Approval</div>
      <div class="signature-line-visual"></div>
      <div class="signature-name">{client_name}</div>
    </div>
    <div class="signature-item">
      <div class="signature-label">Date</div>
      <div class="signature-line-visual"></div>
    </div>
  </div>
  <div class="signature-line">
    <div class="signature-item">
      <div class="signature-label">Company Representative</div>
      <div class="signature-line-visual"></div>
      <div class="signature-name">M&R Outdoor Living Solutions</div>
    </div>
    <div class="signature-item">
      <div class="signature-label">Date</div>
      <div class="signature-line-visual"></div>
    </div>
  </div>
</div>

<!-- FOOTER -->
<div class="footer">
  Miami, Florida · Est. 2019 · 786.283.3179 · mroutdoorlivingsolution.com
</div>

</div></body></html>"""

    return html

@app.route('/')
def index():
    return render_template('form.html')

@app.route('/generate', methods=['POST'])
def generate():
    """Generate PDF from form data"""
    try:
        data = request.form.to_dict()

        # Validate required fields
        if not data.get('client_name'):
            return jsonify({'error': 'Client name is required'}), 400

        if not data.get('service_type'):
            return jsonify({'error': 'Service type is required'}), 400

        # Handle image uploads (any number, all go on the renderings page)
        images = []
        for file in request.files.getlist('project_image'):
            if not file or not file.filename:
                continue
            image_bytes = file.read()
            if len(image_bytes) > 8 * 1024 * 1024:
                return jsonify({'error': f'{file.filename} is too large (max 8MB)'}), 400
            name = file.filename.lower()
            mime_type = 'image/png' if name.endswith('.png') else 'image/gif' if name.endswith('.gif') else 'image/jpeg'
            images.append(f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('utf-8')}")

        # Additional line items
        extras = []
        for desc, amt in zip(request.form.getlist('extra_desc'), request.form.getlist('extra_amount')):
            desc = desc.strip()
            try:
                amt = float(amt) if amt.strip() else 0.0
            except ValueError:
                return jsonify({'error': f'Invalid amount for line item "{desc}"'}), 400
            extras.append((desc, amt))

        try:
            html_content = generate_estimate_pdf(data, images, extras)
        except Exception as gen_err:
            return jsonify({'error': f'Failed to generate estimate: {str(gen_err)}'}), 400

        # Save HTML temporarily
        tmpdir = tempfile.mkdtemp(prefix='estimate_')
        html_path = os.path.join(tmpdir, 'estimate.html')
        try:
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
        except Exception as write_err:
            return jsonify({'error': f'Failed to save estimate: {str(write_err)}'}), 400

        # Convert to PDF
        pdf_path = os.path.join(tmpdir, 'estimate.pdf')
        result = os.system(f'wkhtmltopdf --quiet --enable-local-file-access {html_path} {pdf_path}')

        if result != 0 or not os.path.exists(pdf_path):
            return jsonify({'error': 'Failed to convert estimate to PDF'}), 400

        return send_file(pdf_path, as_attachment=True, download_name='estimate.pdf')
    except Exception as e:
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(debug=debug, port=port, host='0.0.0.0')
