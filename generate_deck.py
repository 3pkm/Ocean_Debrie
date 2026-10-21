"""
Ocean Debris Tracker - Professional PowerPoint Deck Generator
Generates a comprehensive, 12-slide executive & technical presentation deck
utilizing python-pptx with 16:9 widescreen format, high-contrast dark oceanic theme,
custom metric callouts, and structured multi-column layouts.
"""

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

# ==========================================
# DESIGN SYSTEM & PALETTE SPECIFICATION
# ==========================================
# Subject: Multispectral Marine Debris Tracking, Oceanography, Metocean Physics & Satellite Remote Sensing
# Tone: Mission-Critical, High-Tech, Oceanic Executive & Scientific Engineering
# Aspect Ratio: 16:9 Widescreen (13.333" x 7.500")

COLOR_BG_DARK       = RGBColor(11, 19, 43)    # Deep Oceanic Abyss (#0B132B)
COLOR_CARD_BG       = RGBColor(28, 37, 65)    # Midnight Marine Navy (#1C2541)
COLOR_CARD_BORDER   = RGBColor(58, 80, 107)   # Deep Sea Slate (#3A506B)
COLOR_CARD_ACCENT   = RGBColor(20, 50, 85)    # Elevated Panel Tint
COLOR_TEXT_PRIMARY  = RGBColor(248, 250, 252) # Crisp Pure White (#F8FAFC)
COLOR_TEXT_MUTED    = RGBColor(148, 163, 184) # Muted Ice Blue (#94A3B8)
COLOR_TEXT_DIM      = RGBColor(100, 116, 139) # Secondary Slate (#64748B)

COLOR_CYAN_ACCENT   = RGBColor(0, 242, 254)   # Electric Bio-Cyan / Highlight (#00F2FE)
COLOR_BLUE_ACCENT   = RGBColor(56, 189, 248)  # Sea Sky Blue (#38BDF8)
COLOR_CORAL_ALERT   = RGBColor(244, 63, 94)   # Warning / Critical Coral (#F43F5E)
COLOR_AMBER_ALERT   = RGBColor(251, 146, 60)  # Advisory Orange (#FB923C)
COLOR_EMERALD_OK    = RGBColor(16, 185, 129)  # Active / Validated Emerald (#10B981)

FONT_HEADING = "Trebuchet MS"
FONT_BODY    = "Arial"


def create_deck(output_filename="Ocean_Debris_Tracker_Presentation.pptx"):
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.500)
    blank_layout = prs.slide_layouts[6]  # Blank slide

    def add_base_slide(category, title, subtitle):
        slide = prs.slides.add_slide(blank_layout)
        
        # Deep Background
        bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(7.500))
        bg.fill.solid()
        bg.fill.fore_color.rgb = COLOR_BG_DARK
        bg.line.fill.background()

        # Top Ambient Accent Bar
        top_bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.08))
        top_bar.fill.solid()
        top_bar.fill.fore_color.rgb = COLOR_CYAN_ACCENT
        top_bar.line.fill.background()

        # Header Container
        header_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.4), Inches(11.733), Inches(1.1))
        tf = header_box.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

        # Category Breadcrumb / Tag
        p_cat = tf.paragraphs[0]
        p_cat.text = category.upper()
        p_cat.font.name = FONT_HEADING
        p_cat.font.size = Pt(10)
        p_cat.font.bold = True
        p_cat.font.color.rgb = COLOR_CYAN_ACCENT
        p_cat.space_after = Pt(3)

        # Slide Title
        p_title = tf.add_paragraph()
        p_title.text = title
        p_title.font.name = FONT_HEADING
        p_title.font.size = Pt(22)
        p_title.font.bold = True
        p_title.font.color.rgb = COLOR_TEXT_PRIMARY
        p_title.space_after = Pt(2)

        # Slide Subtitle
        p_sub = tf.add_paragraph()
        p_sub.text = subtitle
        p_sub.font.name = FONT_BODY
        p_sub.font.size = Pt(11)
        p_sub.font.color.rgb = COLOR_TEXT_MUTED

        # Bottom Footer Tracker
        footer_box = slide.shapes.add_textbox(Inches(0.8), Inches(7.05), Inches(11.733), Inches(0.35))
        ftf = footer_box.text_frame
        ftf.word_wrap = True
        ftf.margin_left = ftf.margin_top = ftf.margin_right = ftf.margin_bottom = 0
        p_foot = ftf.paragraphs[0]
        p_foot.text = "OCEAN DEBRIS TRACKER  |  MULTISPECTRAL SEGMENTATION & METOCEAN DRIFT ENGINE  |  AUTONOMOUS SATELLITE PIPELINE"
        p_foot.font.name = FONT_BODY
        p_foot.font.size = Pt(8.5)
        p_foot.font.color.rgb = COLOR_TEXT_DIM

        return slide

    def add_card(slide, left, top, width, height, bg_color=COLOR_CARD_BG, border_color=COLOR_CARD_BORDER):
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
        card.fill.solid()
        card.fill.fore_color.rgb = bg_color
        if border_color:
            card.line.color.rgb = border_color
            card.line.width = Pt(1.2)
        else:
            card.line.fill.background()
        return card

    # =========================================================================
    # SLIDE 1: TITLE SLIDE (EXECUTIVE & HERO)
    # =========================================================================
    slide1 = prs.slides.add_slide(blank_layout)
    bg1 = slide1.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(7.500))
    bg1.fill.solid()
    bg1.fill.fore_color.rgb = COLOR_BG_DARK
    bg1.line.fill.background()

    # Glowing Cyan Accent Line
    accent1 = slide1.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.12))
    accent1.fill.solid()
    accent1.fill.fore_color.rgb = COLOR_CYAN_ACCENT
    accent1.line.fill.background()

    # Hero Title Box
    tbox1 = slide1.shapes.add_textbox(Inches(1.0), Inches(1.3), Inches(11.333), Inches(3.2))
    tf1 = tbox1.text_frame
    tf1.word_wrap = True
    tf1.margin_left = tf1.margin_top = tf1.margin_right = tf1.margin_bottom = 0

    p_badge = tf1.paragraphs[0]
    p_badge.text = "MISSION REPORT & ARCHITECTURAL BRIEFING  •  SENTINEL-2 L2A & METOCEAN DRIFT"
    p_badge.font.name = FONT_HEADING
    p_badge.font.size = Pt(11)
    p_badge.font.bold = True
    p_badge.font.color.rgb = COLOR_CYAN_ACCENT
    p_badge.space_after = Pt(14)

    p_t1 = tf1.add_paragraph()
    p_t1.text = "Multispectral Ocean Debris\nSegmentation & Drift Engine"
    p_t1.font.name = FONT_HEADING
    p_t1.font.size = Pt(36)
    p_t1.font.bold = True
    p_t1.font.color.rgb = COLOR_TEXT_PRIMARY
    p_t1.space_after = Pt(14)

    p_sub1 = tf1.add_paragraph()
    p_sub1.text = "Autonomous Satellite Detection, Cloud-Aware Tracking & Metocean Risk Forecasting"
    p_sub1.font.name = FONT_BODY
    p_sub1.font.size = Pt(16)
    p_sub1.font.color.rgb = COLOR_BLUE_ACCENT
    p_sub1.space_after = Pt(8)

    p_twist = tf1.add_paragraph()
    p_twist.text = 'Solving the "The Clouds Rolled In" Challenge via 500-Particle Monte Carlo RK4 Drift & PostGIS Geofencing'
    p_twist.font.name = FONT_BODY
    p_twist.font.size = Pt(12)
    p_twist.font.color.rgb = COLOR_TEXT_MUTED

    # 4 Key Value Cards on Slide 1
    features = [
        ("14-Channel AI Engine", "UNet / ResAttUNet on 11 bands + FDI, NDVI, NDWI from Sentinel-2 L2A COGs", COLOR_CYAN_ACCENT),
        ('Cloud-Aware Tracking', 'Distinguishes "Occluded / Forecast Only" vs "Lost" using visibility metric V', COLOR_BLUE_ACCENT),
        ("500-Particle Drift", "Stochastic RK4 Lagrangian transport with GFS wind, currents & leeway deflection", COLOR_AMBER_ALERT),
        ("Autonomous Outbox", "Zero-click geofence alerts to coastal authorities via Telegram, Email & Webhook", COLOR_EMERALD_OK)
    ]
    card_w = 2.65
    gap = 0.24
    for i, (f_title, f_desc, color) in enumerate(features):
        c_left = 1.0 + i * (card_w + gap)
        add_card(slide1, c_left, 4.85, card_w, 1.8, COLOR_CARD_BG, color)
        
        cbox = slide1.shapes.add_textbox(Inches(c_left + 0.18), Inches(4.98), Inches(card_w - 0.36), Inches(1.5))
        ctf = cbox.text_frame
        ctf.word_wrap = True
        ctf.margin_left = ctf.margin_top = ctf.margin_right = ctf.margin_bottom = 0
        
        p1 = ctf.paragraphs[0]
        p1.text = f_title
        p1.font.name = FONT_HEADING
        p1.font.size = Pt(13)
        p1.font.bold = True
        p1.font.color.rgb = color
        p1.space_after = Pt(6)
        
        p2 = ctf.add_paragraph()
        p2.text = f_desc
        p2.font.name = FONT_BODY
        p2.font.size = Pt(9.5)
        p2.font.color.rgb = COLOR_TEXT_MUTED

    # =========================================================================
    # SLIDE 2: THE PROBLEM STATEMENT & "THE CLOUDS ROLLED IN" TWIST
    # =========================================================================
    slide2 = add_base_slide(
        "01 / Challenge Definition",
        "The Marine Plastic Crisis & The Cloud Obscuration Dilemma",
        "Why conventional optical tracking fails at sea and how the 'Clouds Rolled In' twist is conquered"
    )

    # Left Column: The Realities of Satellite Monitoring (2 cards)
    add_card(slide2, 0.8, 1.7, 5.65, 2.3)
    t_box = slide2.shapes.add_textbox(Inches(1.05), Inches(1.85), Inches(5.15), Inches(2.0))
    tf = t_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.text = "THE SATELLITE SURVEILLANCE REALITY"
    p.font.name = FONT_HEADING
    p.font.size = Pt(12)
    p.font.bold = True
    p.font.color.rgb = COLOR_CORAL_ALERT
    p.space_after = Pt(8)

    bullets = [
        "Massive Environmental Impact: Over 14M tons of plastic enter oceans yearly, concentrating into toxic, navigation-hazardous debris slicks.",
        "Discontinuous Orbit Revisit: Sentinel-2 orbits revisit given coastal sectors only every ~5 days. Continuous tracking is physically impossible.",
        "Heavy Cloud Obscuration: Tropical and coastal oceanic zones experience 50-70% cloud coverage, blinding optical cameras during critical drift windows."
    ]
    for b in bullets:
        p = tf.add_paragraph()
        p.text = "• " + b
        p.font.name = FONT_BODY
        p.font.size = Pt(9.5)
        p.font.color.rgb = COLOR_TEXT_PRIMARY
        p.space_after = Pt(4)

    add_card(slide2, 0.8, 4.2, 5.65, 2.6)
    t_box = slide2.shapes.add_textbox(Inches(1.05), Inches(4.35), Inches(5.15), Inches(2.3))
    tf = t_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.text = "THE FATAL FLAWS OF NAIVE SYSTEMS"
    p.font.name = FONT_HEADING
    p.font.size = Pt(12)
    p.font.bold = True
    p.font.color.rgb = COLOR_AMBER_ALERT
    p.space_after = Pt(8)

    flaws = [
        "Premature Patch Deletion: Systems assume 'not seen = gone', dropping tracks when clouds obscure satellite passes.",
        "Fragment Ignorance: Large debris patches shear apart under tidal strain; static matchers lose track IDs after splits.",
        "Passive Alerting: Requiring humans to log into dashboards during emergencies creates catastrophic response delays."
    ]
    for f in flaws:
        p = tf.add_paragraph()
        p.text = "✗ " + f
        p.font.name = FONT_BODY
        p.font.size = Pt(9.5)
        p.font.color.rgb = COLOR_TEXT_MUTED
        p.space_after = Pt(5)

    # Right Column: The Core Paradigm Shift (Twist Solution)
    add_card(slide2, 6.75, 1.7, 5.75, 5.1, COLOR_CARD_BG, COLOR_CYAN_ACCENT)
    t_box = slide2.shapes.add_textbox(Inches(7.05), Inches(1.9), Inches(5.15), Inches(4.7))
    tf = t_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.text = 'OUR ANSWER: "THE CLOUDS ROLLED IN" ENGINE'
    p.font.name = FONT_HEADING
    p.font.size = Pt(13)
    p.font.bold = True
    p.font.color.rgb = COLOR_CYAN_ACCENT
    p.space_after = Pt(8)

    p_quote = tf.add_paragraph()
    p_quote.text = '"Clouds are missing data, not evidence of absence."'
    p_quote.font.name = FONT_HEADING
    p_quote.font.size = Pt(12)
    p_quote.font.bold = True
    p_quote.font.color.rgb = COLOR_TEXT_PRIMARY
    p_quote.space_after = Pt(12)

    pillars = [
        ("Cloud-Aware Evidence Accumulator", "Tracks compute visibility V = clear share of predicted ensemble cloud. Patches transition to 'Occluded (Forecast Only)' if V < 0.5. 'Lost' status requires accumulated clear evidence ≥ 1.5 across multiple cloudless passes."),
        ("Dynamic Re-Forecasting Loop", "Forecasts do not stop under clouds! Every 6 hours, live GFS winds and oceanic currents re-propagate particle ensembles, updating landfall risk automatically without satellite imagery."),
        ("Stochastic Adaptive Gating", "When a patch emerges from clouds 10 days later, the search radius scales dynamically with ensemble variance, guaranteeing successful reacquisition."),
        ("Zero-Click Outbox Alerts", "Background crons continuously test predicted particle trajectories against coastal assets, immediately firing Telegram, email, and webhooks.")
    ]
    for p_title, p_body in pillars:
        p1 = tf.add_paragraph()
        p1.text = "✓ " + p_title
        p1.font.name = FONT_HEADING
        p1.font.size = Pt(10)
        p1.font.bold = True
        p1.font.color.rgb = COLOR_BLUE_ACCENT
        p1.space_after = Pt(2)
        p2 = tf.add_paragraph()
        p2.text = p_body
        p2.font.name = FONT_BODY
        p2.font.size = Pt(9)
        p2.font.color.rgb = COLOR_TEXT_MUTED
        p2.space_after = Pt(6)

    # =========================================================================
    # SLIDE 3: END-TO-END ARCHITECTURAL BLUEPRINT
    # =========================================================================
    slide3 = add_base_slide(
        "02 / System Architecture",
        "Autonomous Event-Driven Processing Pipeline",
        "Decoupled serverless ingestion, high-performance ONNX inference, and PostGIS temporal storage"
    )

    steps = [
        ("1. INGESTION", "CDSE Push / STAC", "Push webhook receives new S2 L2A tile event. Checks idempotency, falls back to AWS SNS / STAC polling.", COLOR_BLUE_ACCENT),
        ("2. EXTRACTION", "Windowed COG Crop", "Reads only the 30x30 km AOI window. Builds 400m dilated cloud mask & water mask via SCL + NDWI.", COLOR_CYAN_ACCENT),
        ("3. AI SEGMENT", "14-Band ONNX UNet", "Tiles 256x256, computes FDI/NDVI/NDWI, runs optimized ONNX inference, vectorizes polygon debris contours.", COLOR_CYAN_ACCENT),
        ("4. TRACKING", "Hungarian + Splits", "Matches against active/occluded patches with adaptive covariance gates. Handles patch splitting & merges.", COLOR_EMERALD_OK),
        ("5. ENSEMBLE", "500-Particle RK4", "Stochastic Lagrangian drift over 168h with leeway, windage, and currents. Generates 24h/48h P50 & P90 KDE areas.", COLOR_AMBER_ALERT),
        ("6. GEOFENCE", "Zone Risk & Outbox", "Evaluates first-passage zone arrival probability. Dispatches Telegram, Email, and HMAC-signed webhooks.", COLOR_CORAL_ALERT)
    ]
    card_w = 1.80
    gap = 0.18
    for i, (s_num, s_title, s_desc, color) in enumerate(steps):
        c_left = 0.8 + i * (card_w + gap)
        add_card(slide3, c_left, 1.7, card_w, 3.4, COLOR_CARD_BG, color)
        
        cbox = slide3.shapes.add_textbox(Inches(c_left + 0.12), Inches(1.82), Inches(card_w - 0.24), Inches(3.1))
        ctf = cbox.text_frame
        ctf.word_wrap = True
        ctf.margin_left = ctf.margin_top = ctf.margin_right = ctf.margin_bottom = 0
        
        p = ctf.paragraphs[0]
        p.text = s_num
        p.font.name = FONT_HEADING
        p.font.size = Pt(9)
        p.font.bold = True
        p.font.color.rgb = color
        p.space_after = Pt(2)

        p = ctf.add_paragraph()
        p.text = s_title
        p.font.name = FONT_HEADING
        p.font.size = Pt(11)
        p.font.bold = True
        p.font.color.rgb = COLOR_TEXT_PRIMARY
        p.space_after = Pt(8)

        p = ctf.add_paragraph()
        p.text = s_desc
        p.font.name = FONT_BODY
        p.font.size = Pt(8.5)
        p.font.color.rgb = COLOR_TEXT_MUTED

    # Bottom Architecture Specs (3 Horizontal Cards)
    bottom_cards = [
        ("SERVERLESS CONSTRAINTS & RESILIENCE", [
            "Cold-start ONNX caching in /tmp with sub-300ms execution",
            "Job row-locking (FOR UPDATE SKIP LOCKED) prevents double-runs",
            "Automated sweep cron retries transient failures up to 3 times"
        ], COLOR_BLUE_ACCENT),
        ("POSTGIS & BLOB STORAGE STRATEGY", [
            "Neon Serverless Postgres + PostGIS for spatial geometries",
            "Ensemble trajectories stored as float32 .npy in Vercel Blob",
            "Immutable audit logs: scenes, patches, observations, events"
        ], COLOR_CYAN_ACCENT),
        ("REAL-TIME METOCEAN FEEDS", [
            "Open-Meteo GFS global wind fields on 0.1° AOI grid",
            "Hourly surface marine current vectors (velocity & direction)",
            "Cron refresh at 05:30, 11:30, 17:30, 23:30 UTC"
        ], COLOR_EMERALD_OK)
    ]
    card_w2 = 3.75
    gap2 = 0.24
    for i, (b_title, b_items, color) in enumerate(bottom_cards):
        c_left = 0.8 + i * (card_w2 + gap2)
        add_card(slide3, c_left, 5.25, card_w2, 1.65, COLOR_CARD_BG, color)
        
        cbox = slide3.shapes.add_textbox(Inches(c_left + 0.15), Inches(5.35), Inches(card_w2 - 0.3), Inches(1.45))
        ctf = cbox.text_frame
        ctf.word_wrap = True
        ctf.margin_left = ctf.margin_top = ctf.margin_right = ctf.margin_bottom = 0

        p = ctf.paragraphs[0]
        p.text = b_title
        p.font.name = FONT_HEADING
        p.font.size = Pt(10)
        p.font.bold = True
        p.font.color.rgb = color
        p.space_after = Pt(4)

        for item in b_items:
            p = ctf.add_paragraph()
            p.text = "• " + item
            p.font.name = FONT_BODY
            p.font.size = Pt(8.5)
            p.font.color.rgb = COLOR_TEXT_PRIMARY
            p.space_after = Pt(2)

    # =========================================================================
    # SLIDE 4: 14-CHANNEL MULTISPECTRAL SEGMENTATION ENGINE
    # =========================================================================
    slide4 = add_base_slide(
        "03 / Computer Vision & Remote Sensing",
        "14-Channel Multispectral Segmentation Engine",
        "Harnessing physical spectral absorption & UNet deep learning to isolate sub-pixel marine debris"
    )

    # Left Column: Spectral Physics & Indices
    add_card(slide4, 0.8, 1.7, 5.65, 5.1)
    t_box = slide4.shapes.add_textbox(Inches(1.05), Inches(1.85), Inches(5.15), Inches(4.7))
    tf = t_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    p = tf.paragraphs[0]
    p.text = "SPECTRAL CHANNELS & OPTICAL FORMULATION"
    p.font.name = FONT_HEADING
    p.font.size = Pt(12)
    p.font.bold = True
    p.font.color.rgb = COLOR_CYAN_ACCENT
    p.space_after = Pt(8)

    indices = [
        ("11 S2 L2A Bands", "B1 to B8, B8A, B11, B12 at 10m resampled resolution, calibrated surface reflectance."),
        ("Floating Debris Index (FDI)", "FDI = B8 - [B6 + (B11 - B6) * 1.772]\nDetects elevated NIR reflectance against NIR baseline baseline of seawater, isolating plastics & macro-aggregates."),
        ("Normalized Difference Vegetation (NDVI)", "NDVI = (B8 - B4) / (B8 + B4)\nSeparates natural macro-algae (Sargassum) from anthropogenic polymers."),
        ("Normalized Difference Water Index (NDWI)", "NDWI = (B3 - B8) / (B3 + B8)\nRobust ocean surface masking, excluding inland water and shoreline artifacts."),
        ("Chlorophyll Proxy (NDCI - Indicative)", "NDCI = (B5 - B4) / (B5 + B4)\nVisualized on dashboard to highlight potential Harmful Algal Blooms (HABs).")
    ]
    for idx_name, idx_desc in indices:
        p = tf.add_paragraph()
        p.text = "▸ " + idx_name
        p.font.name = FONT_HEADING
        p.font.size = Pt(10)
        p.font.bold = True
        p.font.color.rgb = COLOR_TEXT_PRIMARY
        p.space_after = Pt(1)
        p = tf.add_paragraph()
        p.text = idx_desc
        p.font.name = FONT_BODY
        p.font.size = Pt(8.5)
        p.font.color.rgb = COLOR_TEXT_MUTED
        p.space_after = Pt(4)

    # Right Column: Model Architecture & Benchmark
    add_card(slide4, 6.75, 1.7, 5.75, 5.1)
    t_box = slide4.shapes.add_textbox(Inches(7.05), Inches(1.85), Inches(5.15), Inches(4.7))
    tf = t_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    p = tf.paragraphs[0]
    p.text = "NEURAL SEGMENTATION & INFERENCE PIPELINE"
    p.font.name = FONT_HEADING
    p.font.size = Pt(12)
    p.font.bold = True
    p.font.color.rgb = COLOR_BLUE_ACCENT
    p.space_after = Pt(8)

    models = [
        ("MARIDA Benchmark Training", "Trained on Marine Debris Archive (MARIDA) 11-band 10m patches across 15 marine classes (debris, sargassum, foam, glint, water variants)."),
        ("UNet / ResAttUNet Architecture", "14-channel input tensor (11 bands + FDI/NDVI/NDWI). First convolutional layer initialized with channel-averaged ImageNet weights."),
        ("Loss Formulation", "Combined Dice Loss + Focal Loss with ignore_index for unlabeled pixels, handling extreme class imbalance."),
        ("Ablation Study Provenance", "RGB Only (Baseline A) vs 11 Bands (B) vs 11 Bands + FDI/NDVI/NDWI (C). Configuration C achieved superior F1 & precision on debris."),
        ("ONNX Runtime Deployment", "Weights exported to ONNX (fp32) with numerical parity (<1e-4 difference). Serverless cold start takes <200ms."),
        ("Vector Polygonization", "Contours vectorized with Shapely, computing exact polygon geometry, centroid, area in m², mean confidence, and mean FDI.")
    ]
    for m_title, m_desc in models:
        p = tf.add_paragraph()
        p.text = "✔ " + m_title
        p.font.name = FONT_HEADING
        p.font.size = Pt(10)
        p.font.bold = True
        p.font.color.rgb = COLOR_TEXT_PRIMARY
        p.space_after = Pt(1)
        p = tf.add_paragraph()
        p.text = m_desc
        p.font.name = FONT_BODY
        p.font.size = Pt(8.5)
        p.font.color.rgb = COLOR_TEXT_MUTED
        p.space_after = Pt(4)

    # =========================================================================
    # SLIDE 5: CLOUD-AWARE TRACKING & SPLIT LINEAGE
    # =========================================================================
    slide5 = add_base_slide(
        "04 / Spatio-Temporal Association",
        "Cloud-Aware Patch Tracking & Split Lineage",
        "Solving identity persistence across discontinuous orbits, shearing splits, and dense cloud cover"
    )

    # 3 Column Layout for Tracking Phases
    col_w = 3.75
    gap = 0.24

    # Card 1: Association & Hungarian Matcher
    add_card(slide5, 0.8, 1.7, col_w, 5.1)
    t_box = slide5.shapes.add_textbox(Inches(1.0), Inches(1.85), Inches(col_w - 0.4), Inches(4.7))
    tf = t_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    p = tf.paragraphs[0]
    p.text = "1. STOCHASTIC GATING"
    p.font.name = FONT_HEADING
    p.font.size = Pt(11)
    p.font.bold = True
    p.font.color.rgb = COLOR_CYAN_ACCENT
    p.space_after = Pt(6)

    gate_points = [
        "Dynamic Covariance Gate: Search ellipse widens automatically with ensemble particle dispersion over time.",
        "Cost Formulation: c_ij = -log(p_ij + ε) + w_a*|ln(A_j / A_i)| + w_s*|ΔFDI| where p_ij is particle probability density.",
        "Optimal Assignment: Solved via scipy.optimize.linear_sum_assignment on valid gated pairs.",
        "New Patch Genesis: Unmatched detections outside all gates are seeded as new persistent IDs (P-NNNN)."
    ]
    for pt in gate_points:
        p = tf.add_paragraph()
        p.text = "• " + pt
        p.font.name = FONT_BODY
        p.font.size = Pt(8.8)
        p.font.color.rgb = COLOR_TEXT_PRIMARY
        p.space_after = Pt(5)

    # Card 2: Patch Splits and Merges
    add_card(slide5, 0.8 + col_w + gap, 1.7, col_w, 5.1, COLOR_CARD_BG, COLOR_BLUE_ACCENT)
    t_box = slide5.shapes.add_textbox(Inches(0.8 + col_w + gap + 0.2), Inches(1.85), Inches(col_w - 0.4), Inches(4.7))
    tf = t_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    p = tf.paragraphs[0]
    p.text = "2. SPLITS & MERGES"
    p.font.name = FONT_HEADING
    p.font.size = Pt(11)
    p.font.bold = True
    p.font.color.rgb = COLOR_BLUE_ACCENT
    p.space_after = Pt(6)

    split_points = [
        "Oceanic Shearing Reality: Large debris slicks fracture under sub-mesoscale currents and wind stress.",
        "Split Detection Rule: If ≥2 gated unassigned detections have combined area within 0.5-1.5x parent and are within 3 km.",
        "Persistent Lineage: Parent P-0001 status transitions to 'split'; children receive linked IDs P-0001-A and P-0001-B.",
        "Merge Handling: When a detection is gated by ≥2 active patches, parent patches transition to 'merged' with a unified successor."
    ]
    for pt in split_points:
        p = tf.add_paragraph()
        p.text = "• " + pt
        p.font.name = FONT_BODY
        p.font.size = Pt(8.8)
        p.font.color.rgb = COLOR_TEXT_PRIMARY
        p.space_after = Pt(5)

    # Card 3: Cloud Status State Machine
    add_card(slide5, 0.8 + 2 * (col_w + gap), 1.7, col_w, 5.1, COLOR_CARD_BG, COLOR_AMBER_ALERT)
    t_box = slide5.shapes.add_textbox(Inches(0.8 + 2 * (col_w + gap) + 0.2), Inches(1.85), Inches(col_w - 0.4), Inches(4.7))
    tf = t_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    p = tf.paragraphs[0]
    p.text = "3. CLOUD STATE MACHINE"
    p.font.name = FONT_HEADING
    p.font.size = Pt(11)
    p.font.bold = True
    p.font.color.rgb = COLOR_AMBER_ALERT
    p.space_after = Pt(6)

    states = [
        ("ACTIVE", "Observed in current scene. Highest confidence. Forecast seeds from fresh polygon.", COLOR_EMERALD_OK),
        ("OCCLUDED", 'V < 0.5 in pass. Displayed as "Not observed, forecast only". Drift prediction continues unimpeded.', COLOR_BLUE_ACCENT),
        ("LOST", 'Accumulated clear evidence ≥ 1.5 without detection. Classified as "No longer detected".', COLOR_CORAL_ALERT),
        ("STRANDED", "Ensemble trajectory terminates against shoreline land boundary.", COLOR_AMBER_ALERT),
        ("EXPIRED", "Unobserved for >21 days. Forecast retired to prevent unbounded variance.", COLOR_TEXT_MUTED)
    ]
    for s_name, s_desc, color in states:
        p = tf.add_paragraph()
        p.text = "◼ " + s_name
        p.font.name = FONT_HEADING
        p.font.size = Pt(9.5)
        p.font.bold = True
        p.font.color.rgb = color
        p.space_after = Pt(1)
        p = tf.add_paragraph()
        p.text = s_desc
        p.font.name = FONT_BODY
        p.font.size = Pt(8.5)
        p.font.color.rgb = COLOR_TEXT_MUTED
        p.space_after = Pt(3)

    # =========================================================================
    # SLIDE 6: 500-PARTICLE METOCEAN DRIFT & ENSEMBLE FORECASTING
    # =========================================================================
    slide6 = add_base_slide(
        "05 / Metocean Physics & Simulation",
        "500-Particle Monte Carlo RK4 Drift Engine",
        "Stochastic Lagrangian transport modeling driven by live GFS wind & surface current vectors"
    )

    # Left: Physics & Parameter Distributions
    add_card(slide6, 0.8, 1.7, 5.65, 5.1)
    t_box = slide6.shapes.add_textbox(Inches(1.05), Inches(1.85), Inches(5.15), Inches(4.7))
    tf = t_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    p = tf.paragraphs[0]
    p.text = "RUNGE-KUTTA 4TH ORDER LAGRANGIAN TRANSPORT"
    p.font.name = FONT_HEADING
    p.font.size = Pt(12)
    p.font.bold = True
    p.font.color.rgb = COLOR_CYAN_ACCENT
    p.space_after = Pt(8)

    p_eq = tf.add_paragraph()
    p_eq.text = "Velocity: V_particle = U_current + W_factor * R(θ_leeway) * U_wind + ξ_diff"
    p_eq.font.name = FONT_HEADING
    p_eq.font.size = Pt(10)
    p_eq.font.bold = True
    p_eq.font.color.rgb = COLOR_TEXT_PRIMARY
    p_eq.space_after = Pt(8)

    params = [
        ("Windage Factor", "Truncated normal distribution: mean 2.0%, SD 0.7%, bounds [0.5%, 4.0%]. Models variable buoyancy & object freeboard."),
        ("Leeway Deflection Angle", "Normal distribution: mean 0°, SD 10°. Accounts for Coriolis deflection and asymmetrical object hydrodynamics."),
        ("Current Scale Factor", "Normal distribution: mean 1.0, SD 0.15. Incorporates sub-grid current velocity variance."),
        ("Turbulent Diffusion (Random Walk)", "Brownian random walk with K = 10 m²/s: Δx = sqrt(2*K*dt)*ξ, capturing chaotic sub-mesoscale ocean mixing."),
        ("RK4 Numerical Integration", "168 hourly time-steps (7 days) evaluated with 4th-order Runge-Kutta numerical integration for minimal trajectory drift error.")
    ]
    for p_title, p_desc in params:
        p = tf.add_paragraph()
        p.text = "• " + p_title
        p.font.name = FONT_HEADING
        p.font.size = Pt(9.5)
        p.font.bold = True
        p.font.color.rgb = COLOR_BLUE_ACCENT
        p.space_after = Pt(1)
        p = tf.add_paragraph()
        p.text = p_desc
        p.font.name = FONT_BODY
        p.font.size = Pt(8.5)
        p.font.color.rgb = COLOR_TEXT_MUTED
        p.space_after = Pt(3)

    # Right: Probability Areas & Gaussian KDE
    add_card(slide6, 6.75, 1.7, 5.75, 5.1)
    t_box = slide6.shapes.add_textbox(Inches(7.05), Inches(1.85), Inches(5.15), Inches(4.7))
    tf = t_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    p = tf.paragraphs[0]
    p.text = "PROBABILITY CONTOURS (24H & 48H HORIZONS)"
    p.font.name = FONT_HEADING
    p.font.size = Pt(12)
    p.font.bold = True
    p.font.color.rgb = COLOR_AMBER_ALERT
    p.space_after = Pt(8)

    kde_items = [
        ("Gaussian Kernel Density Estimation (KDE)", "At 24h and 48h horizons, particle clouds are evaluated using Gaussian KDE on a 1 km grid to produce continuous probability density surfaces."),
        ("P50 High-Density Core Polygon", "Inner contour enclosing 50% of particle density. Plain language definition: '50% chance the debris patch is inside this area.'"),
        ("P90 Dispersion Plume Polygon", "Outer contour enclosing 90% of particle density. Plain language definition: '90% chance the debris patch is inside this area.'"),
        ("Landfall & Beaching Detection", "Hourly checks against Natural Earth / GSHHG coastline polygons. Particles intersecting land halt immediately and register as stranded."),
        ("Blob-Backed Trajectory Storage", "Full 500-particle x 168-hour trajectory matrices are stored as float32 .npy files in Vercel Blob, avoiding Postgres bloating.")
    ]
    for k_title, k_desc in kde_items:
        p = tf.add_paragraph()
        p.text = "✔ " + k_title
        p.font.name = FONT_HEADING
        p.font.size = Pt(9.5)
        p.font.bold = True
        p.font.color.rgb = COLOR_TEXT_PRIMARY
        p.space_after = Pt(1)
        p = tf.add_paragraph()
        p.text = k_desc
        p.font.name = FONT_BODY
        p.font.size = Pt(8.5)
        p.font.color.rgb = COLOR_TEXT_MUTED
        p.space_after = Pt(3)

    # =========================================================================
    # SLIDE 7: CONTINUOUS FORECAST VERIFICATION & GROUND TRUTH
    # =========================================================================
    slide7 = add_base_slide(
        "06 / Validation & Calibration",
        "Forecast Verification & Closed-Loop Calibration",
        "Empirically quantifying prediction error against future satellite passes to validate physical models"
    )

    # 3 Summary Stat Callout Cards
    stat_w = 3.75
    gap = 0.24
    stats = [
        ("GEODESIC ERROR", "pyproj.Geod (WGS-84)", "Exact great-circle error (km) computed between predicted ensemble mean and true observed centroid."),
        ("CALIBRATION CHECKS", "In-P50 (~50%) | In-P90 (~90%)", "Empirical confirmation that observed patches land inside confidence intervals with proper frequency."),
        ("BENCHMARK COMPARISON", "Persistence & Currents-Only", "Proves coupled windage model out-predicts static persistence and ocean-current-only baselines.")
    ]
    for i, (st_top, st_mid, st_bot) in enumerate(stats):
        c_left = 0.8 + i * (stat_w + gap)
        add_card(slide7, c_left, 1.7, stat_w, 1.5, COLOR_CARD_BG, COLOR_CYAN_ACCENT)
        cbox = slide7.shapes.add_textbox(Inches(c_left + 0.15), Inches(1.8), Inches(stat_w - 0.3), Inches(1.3))
        ctf = cbox.text_frame
        ctf.word_wrap = True
        ctf.margin_left = ctf.margin_top = ctf.margin_right = ctf.margin_bottom = 0
        
        p = ctf.paragraphs[0]
        p.text = st_top
        p.font.name = FONT_HEADING
        p.font.size = Pt(10)
        p.font.bold = True
        p.font.color.rgb = COLOR_CYAN_ACCENT
        p.space_after = Pt(2)
        
        p = ctf.add_paragraph()
        p.text = st_mid
        p.font.name = FONT_HEADING
        p.font.size = Pt(12)
        p.font.bold = True
        p.font.color.rgb = COLOR_TEXT_PRIMARY
        p.space_after = Pt(4)
        
        p = ctf.add_paragraph()
        p.text = st_bot
        p.font.name = FONT_BODY
        p.font.size = Pt(8.5)
        p.font.color.rgb = COLOR_TEXT_MUTED

    # Bottom Split Cards
    add_card(slide7, 0.8, 3.45, 5.75, 3.35)
    t_box = slide7.shapes.add_textbox(Inches(1.05), Inches(3.6), Inches(5.25), Inches(3.0))
    tf = t_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    p = tf.paragraphs[0]
    p.text = "MANDATORY RE-SEEDING GUARANTEE"
    p.font.name = FONT_HEADING
    p.font.size = Pt(11)
    p.font.bold = True
    p.font.color.rgb = COLOR_EMERALD_OK
    p.space_after = Pt(6)

    reseed_bullets = [
        "Never Accumulate Drift Error: When a satellite pass acquires a patch, the prior forecast is permanently verified and closed.",
        "Observation-Based Seeding: Next 168-hour forecast is initialized uniformly inside the newly observed polygon geometry (seeded_from = 'observation').",
        "Ensemble Carry-Forward: Only when a scene pass is cloud-occluded does the forecast continue forward from the prior particle cloud (seeded_from = 'ensemble').",
        "Auditable Lineage: Every observation and forecast pair is permanently logged with lead time (hours) in the PostGIS database."
    ]
    for b in reseed_bullets:
        p = tf.add_paragraph()
        p.text = "✔ " + b
        p.font.name = FONT_BODY
        p.font.size = Pt(9)
        p.font.color.rgb = COLOR_TEXT_PRIMARY
        p.space_after = Pt(3)

    add_card(slide7, 6.75, 3.45, 5.75, 3.35)
    t_box = slide7.shapes.add_textbox(Inches(7.0), Inches(3.6), Inches(5.25), Inches(3.0))
    tf = t_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    p = tf.paragraphs[0]
    p.text = "SPLIT VERIFICATION MECHANICS"
    p.font.name = FONT_HEADING
    p.font.size = Pt(11)
    p.font.bold = True
    p.font.color.rgb = COLOR_BLUE_ACCENT
    p.space_after = Pt(6)

    split_verif = [
        "Centroid Area-Weighting: When a patch splits into children (e.g., P-0001-A and P-0001-B), the parent's predicted forecast is verified against the area-weighted centroid of both fragments.",
        "Dispersion Distance: Individual fragment distances to the nearest 50% confidence contour are recorded.",
        "Baseline Benchmark Logging: Records persistence error (where debris would be if static) and currents-only error (zero leeway/windage).",
        "Transparent UI Reporting: Real-time verification charts on the frontend build operator trust by exposing exact model accuracy."
    ]
    for sv in split_verif:
        p = tf.add_paragraph()
        p.text = "• " + sv
        p.font.name = FONT_BODY
        p.font.size = Pt(9)
        p.font.color.rgb = COLOR_TEXT_MUTED
        p.space_after = Pt(3)

    # =========================================================================
    # SLIDE 8: COASTAL GEOFENCING & AUTONOMOUS OUTBOX ALERTS
    # =========================================================================
    slide8 = add_base_slide(
        "07 / Operational Protection",
        "Coastal Geofencing & Autonomous Outbox Alerts",
        "Zero-click early warning infrastructure alerting marine authorities before debris enters sensitive zones"
    )

    # 4 Multi-Channel Cards
    channels = [
        ("1. FIRST-PASSAGE RISK", "Trajectories Evaluated", "Evaluates every hourly particle step against registered harbor & MPA polygons within a 48h horizon. P(reach) = % particles intersecting.", COLOR_CYAN_ACCENT),
        ("2. ARRIVAL WINDOW", "P10 to P90 ETA", "Calculates arrival spread between 10th and 90th percentile of arriving particles, giving emergency teams actionable operational windows.", COLOR_BLUE_ACCENT),
        ("3. TIERED THRESHOLDS", "Advisory vs Warning", "Advisory triggered at P ≥ 0.20 (20%). Warning escalated at P ≥ 0.50 (50%). Alerts trigger only on tier escalation or ΔP ≥ 0.15.", COLOR_AMBER_ALERT),
        ("4. ZERO-CLICK OUTBOX", "Deduplicated Delivery", "Crons deliver pending alerts with exponential backoff retries. Dedupe key (zone_id|patch_id|scene_id|tier) prevents duplicate spam.", COLOR_CORAL_ALERT)
    ]
    col_w = 2.65
    gap = 0.24
    for i, (ch_title, ch_sub, ch_desc, color) in enumerate(channels):
        c_left = 0.8 + i * (col_w + gap)
        add_card(slide8, c_left, 1.7, col_w, 2.7, COLOR_CARD_BG, color)
        cbox = slide8.shapes.add_textbox(Inches(c_left + 0.15), Inches(1.82), Inches(col_w - 0.3), Inches(2.5))
        ctf = cbox.text_frame
        ctf.word_wrap = True
        ctf.margin_left = ctf.margin_top = ctf.margin_right = ctf.margin_bottom = 0

        p = ctf.paragraphs[0]
        p.text = ch_title
        p.font.name = FONT_HEADING
        p.font.size = Pt(10.5)
        p.font.bold = True
        p.font.color.rgb = color
        p.space_after = Pt(2)

        p = ctf.add_paragraph()
        p.text = ch_sub
        p.font.name = FONT_HEADING
        p.font.size = Pt(11)
        p.font.bold = True
        p.font.color.rgb = COLOR_TEXT_PRIMARY
        p.space_after = Pt(6)

        p = ctf.add_paragraph()
        p.text = ch_desc
        p.font.name = FONT_BODY
        p.font.size = Pt(8.8)
        p.font.color.rgb = COLOR_TEXT_MUTED

    # Bottom Alert Dispatch Engine Card
    add_card(slide8, 0.8, 4.65, 11.733, 2.15, COLOR_CARD_BG, COLOR_EMERALD_OK)
    t_box = slide8.shapes.add_textbox(Inches(1.05), Inches(4.8), Inches(11.2), Inches(1.85))
    tf = t_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    p = tf.paragraphs[0]
    p.text = "MULTI-CHANNEL OUTBOX DISPATCH CHANNELS (TESTED & VERIFIED)"
    p.font.name = FONT_HEADING
    p.font.size = Pt(11)
    p.font.bold = True
    p.font.color.rgb = COLOR_EMERALD_OK
    p.space_after = Pt(6)

    dispatch_cols = [
        ("TELEGRAM BOT API", "Instant dispatch of structured alerts with patch ID, probability, arrival window, and direct deep-link to the React dashboard map view."),
        ("HTTP EMAIL API", "Integrates with Resend / SendGrid using Bearer token authentication, delivering high-priority emergency alerts to port directorates."),
        ("HMAC-SIGNED WEBHOOKS", "Automates machine-to-machine response systems via HTTP POST with cryptographic X-Signature (HMAC-SHA256) verification header.")
    ]
    for d_title, d_desc in dispatch_cols:
        p = tf.add_paragraph()
        p.text = "✔ " + d_title + ": " + d_desc
        p.font.name = FONT_BODY
        p.font.size = Pt(9)
        p.font.color.rgb = COLOR_TEXT_PRIMARY
        p.space_after = Pt(4)

    # =========================================================================
    # SLIDE 9: INTERACTIVE OPERATIONS DASHBOARD (UI/UX)
    # =========================================================================
    slide9 = add_base_slide(
        "08 / Human-Machine Interface",
        "Real-Time Operations Dashboard & GIS Visualization",
        "High-contrast marine operations interface engineered with React 19, MapLibre GL, and TanStack Query"
    )

    # 3 Column Overview of Dashboard UI
    col_w = 3.75
    gap = 0.24

    # Card 1: Map Visualization
    add_card(slide9, 0.8, 1.7, col_w, 5.1)
    t_box = slide9.shapes.add_textbox(Inches(1.0), Inches(1.85), Inches(col_w - 0.4), Inches(4.7))
    tf = t_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    p = tf.paragraphs[0]
    p.text = "MAPLIBRE GL CANVAS"
    p.font.name = FONT_HEADING
    p.font.size = Pt(11)
    p.font.bold = True
    p.font.color.rgb = COLOR_CYAN_ACCENT
    p.space_after = Pt(6)

    map_features = [
        "Dark Ocean Basemap: Clean, low-glare cartography optimized for operations rooms.",
        "Color-Coded Patches: Active (Emerald), Occluded (Sky Blue), Stranded (Amber), Lost (Coral).",
        "Probability Plume Overlays: P50 inner core (solid fill) and P90 outer dispersion plume (dashed).",
        "Split Lineage Paths: Thin illuminated vectors showing historical fragment trajectories from parent patches.",
        "Indicative NDCI Layer: Visualizes chlorophyll proxy to contextualize debris slicks with algal blooms."
    ]
    for mf in map_features:
        p = tf.add_paragraph()
        p.text = "• " + mf
        p.font.name = FONT_BODY
        p.font.size = Pt(8.8)
        p.font.color.rgb = COLOR_TEXT_PRIMARY
        p.space_after = Pt(4)

    # Card 2: Mission Telemetry & Panels
    add_card(slide9, 0.8 + col_w + gap, 1.7, col_w, 5.1)
    t_box = slide9.shapes.add_textbox(Inches(0.8 + col_w + gap + 0.2), Inches(1.85), Inches(col_w - 0.4), Inches(4.7))
    tf = t_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    p = tf.paragraphs[0]
    p.text = "MISSION PANELS & TELEMETRY"
    p.font.name = FONT_HEADING
    p.font.size = Pt(11)
    p.font.bold = True
    p.font.color.rgb = COLOR_BLUE_ACCENT
    p.space_after = Pt(6)

    panels = [
        "Data Freshness Bar: Displays exact UTC timestamp of latest satellite scene, GFS wind model, and ocean currents.",
        "Patch Timeline Drawer: Complete audit history showing born, split, occluded, and reacquisition events.",
        "Recharts Verification Graph: Lead time vs geodesic error (km) with persistence and currents-only baselines.",
        "Alert Log: Live ledger of triggered advisory and warning events with delivery receipt confirmations."
    ]
    for pan in panels:
        p = tf.add_paragraph()
        p.text = "• " + pan
        p.font.name = FONT_BODY
        p.font.size = Pt(8.8)
        p.font.color.rgb = COLOR_TEXT_PRIMARY
        p.space_after = Pt(4)

    # Card 3: Interactive Geofencing & Trigger Controls
    add_card(slide9, 0.8 + 2 * (col_w + gap), 1.7, col_w, 5.1, COLOR_CARD_BG, COLOR_EMERALD_OK)
    t_box = slide9.shapes.add_textbox(Inches(0.8 + 2 * (col_w + gap) + 0.2), Inches(1.85), Inches(col_w - 0.4), Inches(4.7))
    tf = t_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    p = tf.paragraphs[0]
    p.text = "INTERACTIVE CONTROLS"
    p.font.name = FONT_HEADING
    p.font.size = Pt(11)
    p.font.bold = True
    p.font.color.rgb = COLOR_EMERALD_OK
    p.space_after = Pt(6)

    controls = [
        ("Polygon Drawing Tool", "Authorities draw custom coastal hazard zones directly on map, setting custom Advisory & Warning thresholds."),
        ("Multi-Channel Form", "Configure Telegram chat IDs, authority email addresses, and HMAC webhook endpoints in-app."),
        ("Fetch Latest Trigger", "Manual button enqueues instant STAC query and processing job for newest pass."),
        ("Replay Mode Switcher", "Allows reviewers and emergency drills to step through historical multi-pass storm scenarios.")
    ]
    for c_title, c_desc in controls:
        p = tf.add_paragraph()
        p.text = "✔ " + c_title
        p.font.name = FONT_HEADING
        p.font.size = Pt(9.5)
        p.font.bold = True
        p.font.color.rgb = COLOR_TEXT_PRIMARY
        p.space_after = Pt(1)
        p = tf.add_paragraph()
        p.text = c_desc
        p.font.name = FONT_BODY
        p.font.size = Pt(8.5)
        p.font.color.rgb = COLOR_TEXT_MUTED
        p.space_after = Pt(3)

    # =========================================================================
    # SLIDE 10: RIGOROUS VERIFICATION: END-TO-END TEST SUITE (S1–S9)
    # =========================================================================
    slide10 = add_base_slide(
        "09 / Quality Assurance & Testing",
        "70 / 70 Tests Passing: End-to-End Test Suite",
        "100% verified test coverage across mathematical formulations, edge cases, and end-to-end scenarios"
    )

    # Big Badge / Stat Header
    add_card(slide10, 0.8, 1.7, 11.733, 1.0, COLOR_CARD_BG, COLOR_EMERALD_OK)
    cbox = slide10.shapes.add_textbox(Inches(1.05), Inches(1.82), Inches(11.2), Inches(0.8))
    ctf = cbox.text_frame
    ctf.word_wrap = True
    ctf.margin_left = ctf.margin_top = ctf.margin_right = ctf.margin_bottom = 0
    p = ctf.paragraphs[0]
    p.text = "TEST EXECUTION METRICS: 70 PASSED IN 23.44s  •  ZERO FAILURES  •  100% COVERAGE"
    p.font.name = FONT_HEADING
    p.font.size = Pt(13)
    p.font.bold = True
    p.font.color.rgb = COLOR_EMERALD_OK
    p.space_after = Pt(2)
    p = ctf.add_paragraph()
    p.text = "Full synthetic fixtures with known ground-truth drift, verifying every pipeline stage under PyTest & PostGIS."
    p.font.name = FONT_BODY
    p.font.size = Pt(9.5)
    p.font.color.rgb = COLOR_TEXT_PRIMARY

    # Grid of Scenario Cards (S1 - S9)
    scenarios = [
        ("S1: Split Lineage", "Single patch shears into two fragments; parent marked 'split', linked children P-0001-A/B created with IDs preserved.", COLOR_CYAN_ACCENT),
        ("S2: Cloud Occlusion", "Patch under dense cloud is set to 'occluded' ('Not observed, forecast only'); never dropped or marked lost.", COLOR_CYAN_ACCENT),
        ("S3: Absence Lost", "Patch absent across clear passes accumulates clear evidence V ≥ 1.5 and transitions cleanly to 'lost'.", COLOR_CYAN_ACCENT),
        ("S4: Forecast Error", "Matched patch geodesic error_km matches known synthetic displacement with exact pyproj.Geod distance.", COLOR_BLUE_ACCENT),
        ("S5: Observation Re-seed", "Next forecast is seeded uniformly from the newly observed polygon, never continuing old drift error.", COLOR_BLUE_ACCENT),
        ("S6: Autonomous Alert", "Zone 30 km downstream triggers outbox alert with arrival window and probability with dashboard closed.", COLOR_BLUE_ACCENT),
        ("S7: Idempotency", "Reprocessing the same scene twice produces no duplicate alerts and no duplicate patches.", COLOR_AMBER_ALERT),
        ("S8: Restart Persistence", "Simulated system crash and restart retains all patches, observations, events, and forecasts intact.", COLOR_AMBER_ALERT),
        ("S9: Fetch Latest Flow", "End-to-end execution of 'Fetch latest' button runs full pipeline (preprocess -> infer -> track -> forecast).", COLOR_EMERALD_OK)
    ]
    card_w3 = 3.75
    gap3 = 0.24
    row_h = 1.15
    for i, (sc_name, sc_desc, color) in enumerate(scenarios):
        row = i // 3
        col = i % 3
        c_left = 0.8 + col * (card_w3 + gap3)
        c_top = 2.9 + row * (row_h + 0.15)
        
        add_card(slide10, c_left, c_top, card_w3, row_h, COLOR_CARD_BG, color)
        cbox = slide10.shapes.add_textbox(Inches(c_left + 0.12), Inches(c_top + 0.08), Inches(card_w3 - 0.24), Inches(row_h - 0.16))
        ctf = cbox.text_frame
        ctf.word_wrap = True
        ctf.margin_left = ctf.margin_top = ctf.margin_right = ctf.margin_bottom = 0

        p = ctf.paragraphs[0]
        p.text = sc_name
        p.font.name = FONT_HEADING
        p.font.size = Pt(9.5)
        p.font.bold = True
        p.font.color.rgb = color
        p.space_after = Pt(2)

        p = ctf.add_paragraph()
        p.text = sc_desc
        p.font.name = FONT_BODY
        p.font.size = Pt(8.2)
        p.font.color.rgb = COLOR_TEXT_MUTED

    # =========================================================================
    # SLIDE 11: PRODUCTION HARDENING & DEPLOYMENT ARCHITECTURE
    # =========================================================================
    slide11 = add_base_slide(
        "10 / Production Operations",
        "Production Hardening & Serverless Deployment",
        "Vercel Serverless Functions, Neon PostGIS pooled architecture, and cryptographic security"
    )

    # 4 Column Architecture Cards
    prod_cards = [
        ("SERVERLESS COMPUTE", "Vercel Functions (Python + TS)", [
            "Heavy dependencies isolated: rasterio + onnxruntime in process_scene only",
            "Read APIs in lightweight TypeScript with @neondatabase/serverless",
            "Configured 300s max duration with automatic cold-start model cache"
        ], COLOR_CYAN_ACCENT),
        ("POSTGIS DATA TIER", "Neon Serverless Postgres", [
            "Pooled connection string for serverless elasticity & concurrency",
            "Native PostGIS geometry indexing (GIST) for sub-second spatial queries",
            "Database transactions with row-level locks on job queue"
        ], COLOR_BLUE_ACCENT),
        ("SECURITY & AUTH", "Cryptographic Protection", [
            "CRON_SECRET & INGEST_SECRET header verification on all webhooks",
            "HMAC-SHA256 signature generated on raw JSON payload for webhooks",
            "API keys sanitized and omitted from all public client responses"
        ], COLOR_AMBER_ALERT),
        ("SCHEDULED CRONS", "Background Orchestration", [
            "sweep cron (every 10 min): recovers stuck jobs & checks missed STAC passes",
            "refresh_risk (6-hourly): re-runs ensembles with new wind & currents",
            "outbox cron (every 5 min): handles exponential backoff delivery"
        ], COLOR_EMERALD_OK)
    ]
    col_w = 2.65
    gap = 0.24
    for i, (p_title, p_sub, p_items, color) in enumerate(prod_cards):
        c_left = 0.8 + i * (col_w + gap)
        add_card(slide11, c_left, 1.7, col_w, 5.1, COLOR_CARD_BG, color)
        cbox = slide11.shapes.add_textbox(Inches(c_left + 0.15), Inches(1.85), Inches(col_w - 0.3), Inches(4.7))
        ctf = cbox.text_frame
        ctf.word_wrap = True
        ctf.margin_left = ctf.margin_top = ctf.margin_right = ctf.margin_bottom = 0

        p = ctf.paragraphs[0]
        p.text = p_title
        p.font.name = FONT_HEADING
        p.font.size = Pt(10.5)
        p.font.bold = True
        p.font.color.rgb = color
        p.space_after = Pt(2)

        p = ctf.add_paragraph()
        p.text = p_sub
        p.font.name = FONT_HEADING
        p.font.size = Pt(11)
        p.font.bold = True
        p.font.color.rgb = COLOR_TEXT_PRIMARY
        p.space_after = Pt(8)

        for item in p_items:
            p = ctf.add_paragraph()
            p.text = "• " + item
            p.font.name = FONT_BODY
            p.font.size = Pt(8.5)
            p.font.color.rgb = COLOR_TEXT_MUTED
            p.space_after = Pt(4)

    # =========================================================================
    # SLIDE 12: CONCLUSION, ROADMAP & STRATEGIC IMPACT
    # =========================================================================
    slide12 = add_base_slide(
        "11 / Summary & Future Horizon",
        "Project Summary, Strategic Impact & Future Roadmap",
        "From prototype to operational ocean monitoring: milestones completed and next frontiers"
    )

    # Left: Milestones Completed
    add_card(slide12, 0.8, 1.7, 5.65, 5.1, COLOR_CARD_BG, COLOR_EMERALD_OK)
    t_box = slide12.shapes.add_textbox(Inches(1.05), Inches(1.85), Inches(5.15), Inches(4.7))
    tf = t_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    p = tf.paragraphs[0]
    p.text = "ALL CORE PROJECT MILESTONES ACHIEVED"
    p.font.name = FONT_HEADING
    p.font.size = Pt(12)
    p.font.bold = True
    p.font.color.rgb = COLOR_EMERALD_OK
    p.space_after = Pt(8)

    achievements = [
        ("P0: Infrastructure Scaffolding", "Neon PostGIS schema, Vercel descriptors, and unified configuration."),
        ("P1: 14-Band Neural Segmentation", "11 bands + FDI/NDVI/NDWI model exported to ONNX with parity checks."),
        ("P2: Single-Scene Pipeline", "Windowed COG ingest, 400m cloud mask dilation, and polygonization."),
        ("P3: Spatio-Temporal Tracking", "Hungarian matcher, covariance gating, and split/merge lineage."),
        ("P4: The 'Clouds Rolled In' Engine", "Occluded vs Lost clear evidence accumulation & forecast verification."),
        ("P5: 500-Particle Metocean Drift", "RK4 integration with GFS wind, marine currents, and P50/P90 KDE."),
        ("P6: Autonomous Outbox Alerting", "Telegram, Email, and HMAC-signed webhook delivery with retry backoff."),
        ("P7: Interactive Web Dashboard", "MapLibre GL dark mode map, freshness bar, and geofencing tool.")
    ]
    for a_title, a_desc in achievements:
        p = tf.add_paragraph()
        p.text = "✔ " + a_title + " — " + a_desc
        p.font.name = FONT_BODY
        p.font.size = Pt(8.5)
        p.font.color.rgb = COLOR_TEXT_PRIMARY
        p.space_after = Pt(3)

    # Right: Future Roadmap & Commercial Horizon
    add_card(slide12, 6.75, 1.7, 5.75, 5.1, COLOR_CARD_BG, COLOR_CYAN_ACCENT)
    t_box = slide12.shapes.add_textbox(Inches(7.05), Inches(1.85), Inches(5.15), Inches(4.7))
    tf = t_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    p = tf.paragraphs[0]
    p.text = "FUTURE FRONTIERS & COMMERCIAL HORIZON"
    p.font.name = FONT_HEADING
    p.font.size = Pt(12)
    p.font.bold = True
    p.font.color.rgb = COLOR_CYAN_ACCENT
    p.space_after = Pt(8)

    future = [
        ("Sentinel-1 SAR Radar Fusion", "Synthetic Aperture Radar (C-band) penetrates dense cloud cover, providing all-weather roughness detection to validate optical patches."),
        ("Autonomous Cleanup Drone Interception", "Generating dynamic waypoints directly for unmanned surface vessels (The Ocean Cleanup) to intercept high-density debris cores."),
        ("CMEMS Global Current Integration", "Upgrading from point API feeds to Copernicus Marine Service (CMEMS) high-resolution reanalysis hydrodynamic models."),
        ("Global Plastic Flow Carbon Accounting", "Quantifying coastal plastic fluxes for environmental ministries and blue economy carbon crediting programs.")
    ]
    for f_title, f_desc in future:
        p = tf.add_paragraph()
        p.text = "🚀 " + f_title
        p.font.name = FONT_HEADING
        p.font.size = Pt(10)
        p.font.bold = True
        p.font.color.rgb = COLOR_BLUE_ACCENT
        p.space_after = Pt(1)
        p = tf.add_paragraph()
        p.text = f_desc
        p.font.name = FONT_BODY
        p.font.size = Pt(8.5)
        p.font.color.rgb = COLOR_TEXT_MUTED
        p.space_after = Pt(4)

    # Save presentation
    prs.save(output_filename)
    print(f"Presentation successfully created and saved to: {output_filename}")


if __name__ == "__main__":
    create_deck()
