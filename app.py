#!/usr/bin/env python3
from flask import Flask, render_template, request, send_file, jsonify
from werkzeug.utils import secure_filename
import os
import pathlib
import base64
import io
from datetime import datetime
import tempfile
import re
import html as html_lib
from PIL import Image, ImageOps
from i18n import STRINGS, SERVICE_ES, format_date

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

# Box each rendering must fit in on the PDF page (inches); two stack per page
IMG_BOX_W, IMG_BOX_H = 7.2, 4.1

def prepare_image(image_bytes):
    """Shrink an upload to a sane size for wkhtmltopdf; return (data URI, width_in, height_in)."""
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert('RGB')
    im.thumbnail((1800, 1800))
    buf = io.BytesIO()
    im.save(buf, 'JPEG', quality=85, optimize=True)
    scale = min(IMG_BOX_W / im.width, IMG_BOX_H / im.height)
    uri = 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()
    return uri, im.width * scale, im.height * scale

# This wkhtmltopdf build lays CSS inches/points out at 1/1.3015 of real size and
# ignores --zoom, so template measurements are scaled up before rendering.
PDF_SCALE = 1.3015

def pdf_units(css):
    return re.sub(r'(-?\d*\.?\d+)(in|pt)\b', lambda m: f"{float(m.group(1)) * PDF_SCALE:.4g}{m.group(2)}", css)

def html_escape(v):
    return html_lib.escape(str(v), quote=True)

def money2(v):
    return "$" + format(v, ",.2f")

def generate_estimate_pdf(data, images=None, extras=None):
    """Generate luxury architectural proposal PDF from form data"""

    client_name = html_escape(data.get('client_name', 'Client'))
    service_type = data.get('service_type', 'general')
    lang = data.get('lang') if data.get('lang') in STRINGS else 'en'
    t = STRINGS[lang]
    completion_time = html_escape(data.get('completion_time') or t['default_completion'])
    start_availability = html_escape(data.get('start_availability') or t['default_start'])
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
    if lang == 'es':
        config = {**config, **SERVICE_ES.get(service_type, SERVICE_ES['general'])}
    option_names = config['option_names']

    grades = [
        (option_names[0], tier1_rate, False),
        (option_names[1], tier2_rate, True),  # Featured/Recommended
        (option_names[2], tier3_rate, False)
    ]

    # Calculate key figures using recommended (tier2) option
    recommended_total = (total_area * tier2_rate) + base_amount + extras_total
    deposit_amount = recommended_total * 0.5

    # NOTE: wkhtmltopdf uses an old WebKit: no CSS grid/flex, and gradients/opacity
    # don't survive some PDF viewers (iOS). Layout is tables + solid colours only.
    now = datetime.now()
    estimate_no = now.strftime('MR-%y%m%d-%H%M')
    project_address = html_escape(data.get('project_address', '').strip())
    addr_html = f"<div class='prep-addr'>{project_address}</div>" if project_address else ""
    featured_name = option_names[1]

    # Page 1: option columns
    option_cells = ""
    for option_name, rate, is_featured in grades:
        total = (total_area * rate) + base_amount + extras_total
        cls = "opt featured" if is_featured else "opt"
        badge = f"<div class='opt-badge'>{t['recommended']}</div>" if is_featured else "<div class='opt-badge-spacer'></div>"
        option_cells += f"""<td class='{cls}'>
          {badge}
          <div class='opt-name'>{option_name}</div>
          <div class='opt-total'>{money2(total)}</div>
          <div class='opt-rate'>${rate:.2f} {t['per_sqft']}</div>
        </td>"""

    # Page 1: highlights (2 x 2)
    highlights = [
        config['inclusions'][1][0],
        config['inclusions'][1][1],
        t['licensed'],
        t['cleanup'],
    ]
    hl = [f"<td class='hl'><span class='hl-dot'></span>{h}</td>" for h in highlights]
    highlights_rows = f"<tr>{hl[0]}{hl[1]}</tr><tr>{hl[2]}{hl[3]}</tr>"

    # Page 3: scope table (recommended option)
    zone_rows = "".join(f"""<tr>
          <td class='t-name'>{html_escape(zone_name)}</td>
          <td class='num t-muted'>{zone_area:,.0f} {t['sqft']}</td>
          <td class='num t-price'>{money2(zone_area * tier2_rate)}</td>
        </tr>""" for zone_name, zone_area in zones)
    base_row = f"""<tr>
          <td class='t-name'>{t['base_prep']}</td>
          <td class='num t-muted'></td>
          <td class='num t-price'>{money2(base_amount)}</td>
        </tr>""" if base_amount else ""
    scope_table = f"""<table class='tbl'>
      <tr><th>{t['area']}</th><th class='num'>{t['size']}</th><th class='num'>{t['cost']} · {featured_name}</th></tr>
      {zone_rows}
      {base_row}
    </table>"""

    extras_section = ""
    if extras:
        rows = "".join(f"""<tr>
          <td class='t-name'>{html_escape(desc)}</td>
          <td class='num t-price'>{money2(amt)}</td>
        </tr>""" for desc, amt in extras)
        extras_section = f"""<div class="block">
  <div class="h2">{t['extras']}</div><div class="h2-bar"></div>
  <table class='tbl'>
    <tr><th>{t['item']}</th><th class='num'>{t['cost']}</th></tr>
    {rows}
    <tr class='t-total'><td>{t['extras_total']}</td><td class='num'>{money2(extras_total)}</td></tr>
  </table>
  <div class='note'>{t['extras_note']}</div>
</div>"""

    inclusion_cols = ""
    for col_idx, column_items in enumerate(config['inclusions']):
        title = t['installation_services'] if col_idx == 0 else t['warranty_support']
        items = "".join(f"<li>{item}</li>" for item in column_items)
        inclusion_cols += f"<td class='inc-col'><div class='inc-title'>{title}</div><ul class='inc'>{items}</ul></td>"

    image_page = ""
    for start in range(0, len(images), 2):
        figures = "".join(f"""<div class="fig"><img src="{uri}" style="width:{w * PDF_SCALE:.2f}in;height:{h * PDF_SCALE:.2f}in" alt=""></div>""" for uri, w, h in images[start:start + 2])
        caption = f'<div class="caption">{t["vision_caption"]}</div>' if start + 2 >= len(images) else ""
        image_page += f"""<div class="pg"><div class="pad">
  <div class="h2">{t['vision']}</div><div class="h2-bar"></div>
  {figures}
  {caption}
</div></div>"""

    contact_bar = f"""<div class="bar">
  <table class="bar-t"><tr>
    <td class="bar-l">M&amp;R Outdoor Living Solutions · (786) 283-3179 · mroutdoorlivingsolution.com</td>
    <td class="bar-r">{t['tagline']}</td>
  </tr></table>
</div>"""

    NAVY_DARK = '#011B3F'
    TINT = '#AFC6E6'
    INK = '#1d2b3a'
    MUTED = '#6b7a8c'
    LINE = '#e3e8ef'
    SOFT = '#f4f7fb'

    css = f"""
* {{ margin:0; padding:0; }}
body {{ font-family:'Montserrat','DejaVu Sans',sans-serif; color:{INK}; font-size:9.5pt; background:#fff; }}
table {{ border-collapse:collapse; width:100%; }}
td, th {{ vertical-align:top; }}
.pg {{ width:8.5in; height:10.98in; position:relative; overflow:hidden; page-break-after:always; background:#fff; }}
.pg.flow {{ height:auto; min-height:10.98in; overflow:visible; }}
.pg.last {{ page-break-after:auto; }}
.pad {{ padding:.55in .65in .6in .65in; }}

/* ---------- PAGE 1 ---------- */
.hero {{ background:{NAVY}; color:#fff; padding:.45in .65in .42in .65in; }}
.hero-top td {{ vertical-align:middle; }}
.logo {{ width:2.5in; }}
.est-meta {{ text-align:right; font-size:8pt; color:{TINT}; line-height:1.7; letter-spacing:.5pt; }}
.est-meta b {{ color:#fff; font-weight:700; }}
.hero-rule {{ height:2px; background:{GREEN}; width:.8in; margin:.32in 0 .2in 0; }}
.kicker {{ font-size:9pt; font-weight:700; letter-spacing:2.5pt; text-transform:uppercase; color:{TINT}; }}
.title {{ font-size:30pt; font-weight:800; line-height:1.08; color:#fff; margin:.08in 0 .28in 0; }}
.prep-label {{ font-size:7.5pt; font-weight:700; letter-spacing:1.5pt; text-transform:uppercase; color:{TINT}; }}
.prep-name {{ font-size:17pt; font-weight:700; color:#fff; margin-top:.05in; }}
.prep-addr {{ font-size:9.5pt; color:{TINT}; margin-top:.04in; }}

.wrap {{ padding:0 .65in; }}
.stats {{ border-bottom:1px solid {LINE}; }}
.stats td {{ width:33.33%; padding:.2in 0 .18in 0; }}
.stats td + td {{ padding-left:.25in; border-left:1px solid {LINE}; }}
.stat-l {{ font-size:7pt; font-weight:700; letter-spacing:1.3pt; text-transform:uppercase; color:{MUTED}; }}
.stat-v {{ font-size:13pt; font-weight:700; color:{NAVY}; margin-top:.05in; }}

.invest-wrap {{ padding:.26in .65in 0 .65in; }}
.invest-l {{ padding-right:.3in; vertical-align:middle; }}
.invest-label {{ font-size:8pt; font-weight:700; letter-spacing:1.3pt; text-transform:uppercase; color:{GREEN}; }}
.invest-amt {{ font-size:40pt; font-weight:800; color:{NAVY}; line-height:1.05; margin:.06in 0 .08in 0; }}
.invest-note {{ font-size:8.5pt; color:{MUTED}; line-height:1.55; }}
.deposit {{ width:2.3in; background:{NAVY}; color:#fff; text-align:center; padding:.26in .15in; vertical-align:middle; }}
.deposit-l {{ font-size:7pt; font-weight:700; letter-spacing:1.3pt; text-transform:uppercase; color:{TINT}; }}
.deposit-amt {{ font-size:22pt; font-weight:800; color:#fff; margin:.06in 0 .04in 0; }}
.deposit-note {{ font-size:7.5pt; color:{TINT}; }}

.opts-wrap {{ padding:.3in .65in 0 .65in; }}
.h3 {{ font-size:8pt; font-weight:700; letter-spacing:1.5pt; text-transform:uppercase; color:{NAVY}; margin-bottom:.12in; }}
.opts-outer {{ margin:0 -.12in; }}
.opts {{ border-collapse:separate; border-spacing:.12in 0; width:100%; }}
.opt {{ width:33.33%; border:1px solid {LINE}; background:{SOFT}; padding:.14in .18in .18in .18in; }}
.opt.featured {{ background:#fff; border:2px solid {GREEN}; }}
.opt-badge {{ display:inline-block; background:{GREEN}; color:#fff; font-size:6.5pt; font-weight:700; letter-spacing:1pt; padding:.03in .09in; margin-bottom:.07in; }}
.opt-badge-spacer {{ height:.17in; margin-bottom:.07in; }}
.opt-name {{ font-size:11pt; font-weight:800; color:{NAVY}; text-transform:uppercase; letter-spacing:.3pt; }}
.opt-total {{ font-size:17pt; font-weight:800; color:{NAVY}; margin:.06in 0 .03in 0; }}
.opt.featured .opt-total {{ color:{GREEN}; }}
.opt-rate {{ font-size:8pt; color:{MUTED}; }}

.hl-wrap {{ padding:.28in .65in 0 .65in; }}
.hl {{ width:50%; font-size:9pt; color:{INK}; padding:.05in 0; }}
.hl-dot {{ display:inline-block; width:.09in; height:.09in; background:{GREEN}; margin-right:.1in; }}

.bar {{ position:absolute; left:0; right:0; bottom:0; background:{NAVY_DARK}; padding:.2in .65in; }}
.bar-t td {{ font-size:7.5pt; color:{TINT}; vertical-align:middle; }}
.bar-r {{ text-align:right; color:#fff; font-weight:600; }}

/* ---------- INNER PAGES ---------- */
.h2 {{ font-size:14pt; font-weight:800; color:{NAVY}; text-transform:uppercase; letter-spacing:.5pt; }}
.h2-bar {{ height:3px; width:.6in; background:{GREEN}; margin:.1in 0 .22in 0; }}
.block {{ margin-bottom:.45in; page-break-inside:avoid; }}
.tbl th {{ font-size:7.5pt; font-weight:700; letter-spacing:1pt; text-transform:uppercase; color:{MUTED}; text-align:left; padding:0 0 .1in 0; border-bottom:2px solid {NAVY}; }}
.tbl td {{ padding:.13in 0; border-bottom:1px solid {LINE}; font-size:9.5pt; }}
.tbl .num {{ text-align:right; }}
.t-name {{ font-weight:600; color:{NAVY}; }}
.t-muted {{ color:{MUTED}; }}
.t-price {{ font-weight:700; color:{NAVY}; }}
.t-total td {{ font-weight:800; color:{NAVY}; border-bottom:none; border-top:2px solid {NAVY}; }}
.note {{ font-size:8pt; color:{MUTED}; margin-top:.08in; }}

.inc-col {{ width:50%; padding-right:.3in; }}
.inc-title {{ font-size:8pt; font-weight:700; letter-spacing:1.2pt; text-transform:uppercase; color:{GREEN}; margin-bottom:.1in; }}
.inc {{ list-style:none; }}
.inc li {{ font-size:9pt; padding:.06in 0 .06in .2in; border-bottom:1px solid {LINE}; position:relative; }}
.inc li:before {{ content:''; position:absolute; left:0; top:.11in; width:.07in; height:.07in; background:{GREEN}; }}

.fig {{ text-align:center; margin-bottom:.2in; }}
.caption {{ text-align:center; font-size:8.5pt; color:{MUTED}; font-style:italic; }}

.terms td {{ width:50%; padding:0 .12in .2in 0; }}
.term {{ background:{SOFT}; border-left:3px solid {GREEN}; padding:.16in .18in; height:.95in; }}
.term-t {{ font-size:7.5pt; font-weight:700; letter-spacing:1pt; text-transform:uppercase; color:{NAVY}; margin-bottom:.06in; }}
.term-c {{ font-size:8.5pt; color:{INK}; line-height:1.55; }}

.sig {{ margin-top:.3in; }}
.sig td {{ padding:0 .3in .35in 0; }}
.sig-line {{ border-bottom:1px solid {NAVY}; height:.45in; }}
.sig-l {{ font-size:7pt; font-weight:700; letter-spacing:1pt; text-transform:uppercase; color:{MUTED}; margin-top:.06in; }}
.sig-n {{ font-size:9pt; font-weight:600; color:{NAVY}; margin-top:.02in; }}
"""

    timeline_value = completion_time
    html = f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<style>{pdf_units(css)}</style></head><body>

<!-- PAGE 1: SUMMARY -->
<div class="pg">
  <div class="hero">
    <table class="hero-top"><tr>
      <td><img class="logo" src="{LOGO}" alt="M&amp;R Outdoor Living Solutions"></td>
      <td class="est-meta">{t['estimate_label']} <b>{estimate_no}</b><br>{format_date(now, lang)}<br>{t['valid_30']}</td>
    </tr></table>
    <div class="hero-rule"></div>
    <div class="kicker">{t['cover_title']}</div>
    <div class="title">{config['subtitle']}</div>
    <div class="prep-label">{t['prepared_for']}</div>
    <div class="prep-name">{client_name}</div>
    {addr_html}
  </div>

  <div class="wrap"><table class="stats"><tr>
    <td><div class="stat-l">{t['project_size']}</div><div class="stat-v">{total_area:,.0f} {t['sqft']}</div></td>
    <td><div class="stat-l">{t['recommended_option']}</div><div class="stat-v">{featured_name}</div></td>
    <td><div class="stat-l">{t['timeline_title']}</div><div class="stat-v">{timeline_value}</div></td>
  </tr></table></div>

  <div class="invest-wrap"><table class="invest"><tr>
    <td class="invest-l">
      <div class="invest-label">{t['your_investment']} · {featured_name}</div>
      <div class="invest-amt">{money2(recommended_total)}</div>
      <div class="invest-note">{t['investment_note']}</div>
    </td>
    <td class="deposit">
      <div class="deposit-l">{t['deposit']}</div>
      <div class="deposit-amt">{money2(deposit_amount)}</div>
      <div class="deposit-note">{t['deposit_note']}</div>
    </td>
  </tr></table></div>

  <div class="opts-wrap">
    <div class="h3">{t['options']}</div>
    <div class="opts-outer"><table class="opts"><tr>{option_cells}</tr></table></div>
  </div>

  <div class="hl-wrap">
    <div class="h3">{t['why_us']}</div>
    <table>{highlights_rows}</table>
  </div>

  {contact_bar}
</div>

{image_page}

<!-- PAGE: SCOPE & INCLUSIONS -->
<div class="pg flow"><div class="pad">
  <div class="block">
    <div class="h2">{t['scope']}</div><div class="h2-bar"></div>
    {scope_table}
  </div>
  {extras_section}
  <div class="block">
    <div class="h2">{t['included']}</div><div class="h2-bar"></div>
    <table><tr>{inclusion_cols}</tr></table>
  </div>
</div></div>

<!-- PAGE: TERMS & APPROVAL -->
<div class="pg last">
<div class="pad">
  <div class="block">
    <div class="h2">{t['terms']}</div><div class="h2-bar"></div>
    <table class="terms">
      <tr>
        <td><div class="term"><div class="term-t">{t['validity_title']}</div><div class="term-c">{t['validity']}</div></div></td>
        <td><div class="term"><div class="term-t">{t['payment_structure_title']}</div><div class="term-c">{t['payment_structure']}</div></div></td>
      </tr>
      <tr>
        <td><div class="term"><div class="term-t">{t['timeline_title']}</div><div class="term-c">{t['timeline'].format(completion=completion_time, start=start_availability)}</div></div></td>
        <td><div class="term"><div class="term-t">{t['payment_methods_title']}</div><div class="term-c">{t['payment_methods']}</div></div></td>
      </tr>
    </table>
  </div>

  <div class="block">
    <div class="h2">{t['approval']}</div><div class="h2-bar"></div>
    <table class="sig">
      <tr>
        <td style="width:62%"><div class="sig-line"></div><div class="sig-l">{t['client_approval']}</div><div class="sig-n">{client_name}</div></td>
        <td><div class="sig-line"></div><div class="sig-l">{t['date']}</div></td>
      </tr>
      <tr>
        <td><div class="sig-line"></div><div class="sig-l">{t['company_rep']}</div><div class="sig-n">M&amp;R Outdoor Living Solutions</div></td>
        <td><div class="sig-line"></div><div class="sig-l">{t['date']}</div></td>
      </tr>
    </table>
  </div>
</div>
{contact_bar}
</div>

</body></html>"""

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
            if len(image_bytes) > 25 * 1024 * 1024:
                return jsonify({'error': f'{file.filename} is too large (max 25MB)'}), 400
            try:
                images.append(prepare_image(image_bytes))
            except Exception:
                return jsonify({'error': f'Could not read image {file.filename}'}), 400

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
        result = os.system(f'wkhtmltopdf --quiet --enable-local-file-access --page-size Letter -T 0 -B 0 -L 0 -R 0 --disable-smart-shrinking --dpi 96 {html_path} {pdf_path}')

        if result != 0 or not os.path.exists(pdf_path):
            return jsonify({'error': 'Failed to convert estimate to PDF'}), 400

        return send_file(pdf_path, as_attachment=True, download_name=f"{STRINGS.get(data.get('lang'), STRINGS['en'])['filename']}.pdf")
    except Exception as e:
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(debug=debug, port=port, host='0.0.0.0')
