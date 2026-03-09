#!/usr/bin/env python3
"""Generate OCR test asset images covering various scenarios."""

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import math

OUT = Path(__file__).parent / "test-assets"
OUT.mkdir(exist_ok=True)

# Try to get a nice font, fall back to default
def get_font(size, bold=False):
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSMono.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    for f in candidates:
        try:
            return ImageFont.truetype(f, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()

def get_mono_font(size):
    candidates = [
        "/System/Library/Fonts/SFNSMono.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Courier.dfont",
    ]
    for f in candidates:
        try:
            return ImageFont.truetype(f, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()

def get_serif_font(size):
    candidates = [
        "/System/Library/Fonts/NewYork.ttf",
        "/System/Library/Fonts/Times.ttc",
        "/Library/Fonts/Times New Roman.ttf",
    ]
    for f in candidates:
        try:
            return ImageFont.truetype(f, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


# ── 1. Simple clean text ─────────────────────────────────────────────

def gen_simple_text():
    img = Image.new("RGB", (800, 400), "#ffffff")
    d = ImageDraw.Draw(img)
    f_title = get_font(36)
    f_body = get_font(22)

    d.text((40, 30), "The Quick Brown Fox", fill="#000000", font=f_title)
    d.text((40, 85), "Jumps over the lazy dog.", fill="#000000", font=f_body)
    d.text((40, 130), "Pack my box with five dozen liquor jugs.", fill="#000000", font=f_body)
    d.text((40, 175), "How vexingly quick daft zebras jump!", fill="#000000", font=f_body)
    d.text((40, 240), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", fill="#333333", font=f_body)
    d.text((40, 280), "abcdefghijklmnopqrstuvwxyz", fill="#333333", font=f_body)
    d.text((40, 320), "0123456789 !@#$%^&*()_+-=", fill="#333333", font=f_body)

    img.save(OUT / "01_simple_text.png")
    print("  Created 01_simple_text.png")


# ── 2. Multi-paragraph article ──────────────────────────────────────

def gen_article():
    img = Image.new("RGB", (800, 600), "#ffffff")
    d = ImageDraw.Draw(img)
    f_h = get_font(28)
    f_body = get_serif_font(18)

    d.text((40, 20), "Climate Change and Global Impact", fill="#111111", font=f_h)
    d.line([(40, 58), (760, 58)], fill="#cccccc", width=1)

    paras = [
        "Global temperatures have risen by approximately 1.1 degrees",
        "Celsius since the pre-industrial era. This warming trend has",
        "accelerated in recent decades, with the last eight years being",
        "the warmest on record.",
        "",
        "The effects of climate change are already being felt across",
        "the planet. Rising sea levels threaten coastal communities,",
        "while extreme weather events are becoming more frequent and",
        "severe in many regions.",
        "",
        "Scientists emphasize that immediate action is needed to limit",
        "warming to 1.5 degrees Celsius above pre-industrial levels,",
        "as outlined in the Paris Agreement of 2015.",
    ]
    y = 75
    for line in paras:
        if line:
            d.text((40, y), line, fill="#222222", font=f_body)
        y += 28

    img.save(OUT / "02_article.png")
    print("  Created 02_article.png")


# ── 3. Receipt / structured data ────────────────────────────────────

def gen_receipt():
    img = Image.new("RGB", (400, 600), "#f5f0e8")
    d = ImageDraw.Draw(img)
    f_title = get_font(22)
    f_mono = get_mono_font(16)
    f_small = get_font(13)

    d.text((120, 20), "SUNRISE CAFE", fill="#000000", font=f_title)
    d.text((130, 50), "456 Oak Avenue", fill="#444444", font=f_small)
    d.text((115, 68), "San Francisco, CA 94102", fill="#444444", font=f_small)
    d.text((130, 86), "Tel: (415) 555-0123", fill="#444444", font=f_small)

    d.line([(30, 110), (370, 110)], fill="#999999", width=1)
    d.text((30, 118), "Date: 2026-03-08  14:32", fill="#000000", font=f_small)
    d.text((30, 136), "Order: #4521", fill="#000000", font=f_small)
    d.line([(30, 158), (370, 158)], fill="#999999", width=1)

    items = [
        ("Espresso Double         ", "$4.50"),
        ("Avocado Toast           ", "$12.95"),
        ("Fresh Orange Juice      ", "$5.50"),
        ("Blueberry Muffin        ", "$3.75"),
        ("Sparkling Water         ", "$2.50"),
    ]
    y = 170
    for name, price in items:
        d.text((30, y), name, fill="#000000", font=f_mono)
        d.text((310, y), price, fill="#000000", font=f_mono)
        y += 28

    d.line([(30, y + 5), (370, y + 5)], fill="#999999", width=1)
    y += 15
    d.text((30, y), "Subtotal", fill="#000000", font=f_mono)
    d.text((310, y), "$29.20", fill="#000000", font=f_mono)
    y += 24
    d.text((30, y), "Tax (8.625%)", fill="#000000", font=f_mono)
    d.text((310, y), "$2.52", fill="#000000", font=f_mono)
    y += 24
    d.line([(30, y), (370, y)], fill="#999999", width=1)
    y += 8
    f_bold = get_font(18)
    d.text((30, y), "TOTAL", fill="#000000", font=f_bold)
    d.text((295, y), "$31.72", fill="#000000", font=f_bold)
    y += 40
    d.text((100, y), "Thank you for visiting!", fill="#666666", font=f_small)
    y += 22
    d.text((130, y), "Have a great day!", fill="#666666", font=f_small)

    img.save(OUT / "03_receipt.png")
    print("  Created 03_receipt.png")


# ── 4. Multi-column layout ──────────────────────────────────────────

def gen_columns():
    img = Image.new("RGB", (900, 500), "#ffffff")
    d = ImageDraw.Draw(img)
    f_h = get_font(24)
    f_body = get_font(15)

    # Title
    d.text((40, 20), "THE DAILY CHRONICLE", fill="#111111", font=get_font(30))
    d.line([(40, 58), (860, 58)], fill="#000000", width=2)
    d.text((40, 65), "Vol. 142, No. 87  |  March 8, 2026  |  $2.50", fill="#666666", font=get_font(12))
    d.line([(40, 85), (860, 85)], fill="#000000", width=1)

    # Column 1
    d.text((40, 100), "Tech Sector Surges", fill="#111111", font=f_h)
    col1 = [
        "Major technology companies",
        "reported record earnings in",
        "the fourth quarter, driven",
        "by strong demand for AI",
        "and cloud computing services.",
        "Analysts predict continued",
        "growth throughout 2026.",
    ]
    y = 135
    for line in col1:
        d.text((40, y), line, fill="#333333", font=f_body)
        y += 22

    # Divider
    d.line([(320, 100), (320, 450)], fill="#cccccc", width=1)

    # Column 2
    d.text((340, 100), "Space Mission Update", fill="#111111", font=f_h)
    col2 = [
        "NASA announced plans for",
        "a new lunar mission set to",
        "launch in late 2027. The",
        "Artemis IV mission will",
        "carry a crew of four to",
        "establish a permanent base",
        "near the Moon's south pole.",
    ]
    y = 135
    for line in col2:
        d.text((340, y), line, fill="#333333", font=f_body)
        y += 22

    # Divider
    d.line([(620, 100), (620, 450)], fill="#cccccc", width=1)

    # Column 3
    d.text((640, 100), "Local Weather", fill="#111111", font=f_h)
    col3 = [
        "Sunny skies expected for",
        "the remainder of the week",
        "with temperatures reaching",
        "highs of 72F (22C). A",
        "slight chance of rain is",
        "forecast for early next",
        "week. UV index: moderate.",
    ]
    y = 135
    for line in col3:
        d.text((640, y), line, fill="#333333", font=f_body)
        y += 22

    img.save(OUT / "04_columns.png")
    print("  Created 04_columns.png")


# ── 5. Handwriting-style (simulated with irregular fonts) ───────────

def gen_handwriting():
    img = Image.new("RGB", (700, 400), "#fffef5")
    d = ImageDraw.Draw(img)
    # Use a cursive-ish font if available, else default
    candidates = [
        "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
        "/System/Library/Fonts/Supplemental/Noteworthy.ttc",
        "/System/Library/Fonts/Supplemental/Comic Sans MS.ttf",
    ]
    f = None
    for c in candidates:
        try:
            f = ImageFont.truetype(c, 26)
            break
        except (OSError, IOError):
            continue
    if f is None:
        f = get_font(26)

    # Draw ruled lines
    for y in range(80, 360, 40):
        d.line([(40, y), (660, y)], fill="#d0d8e8", width=1)

    lines = [
        "Dear Journal,",
        "Today was a wonderful day.",
        "I visited the botanical garden",
        "and saw the cherry blossoms.",
        "The weather was perfect.",
        "Looking forward to tomorrow!",
    ]
    y = 48
    for line in lines:
        d.text((50, y), line, fill="#1a237e", font=f)
        y += 40

    img.save(OUT / "05_handwriting.png")
    print("  Created 05_handwriting.png")


# ── 6. Low contrast / noisy ─────────────────────────────────────────

def gen_low_contrast():
    import random
    img = Image.new("RGB", (600, 300), "#d0d0d0")
    d = ImageDraw.Draw(img)

    # Add noise
    pixels = img.load()
    random.seed(42)
    for x in range(img.width):
        for y in range(img.height):
            r, g, b = pixels[x, y]
            noise = random.randint(-20, 20)
            pixels[x, y] = (
                max(0, min(255, r + noise)),
                max(0, min(255, g + noise)),
                max(0, min(255, b + noise)),
            )

    f = get_font(22)
    # Low contrast text
    d.text((40, 30), "This text has low contrast", fill="#a0a0a0", font=f)
    d.text((40, 70), "and a noisy background.", fill="#a0a0a0", font=f)
    # Medium contrast
    d.text((40, 130), "This line is slightly easier", fill="#707070", font=f)
    d.text((40, 170), "to read than the lines above.", fill="#707070", font=f)
    # Higher contrast
    d.text((40, 230), "This line should be easiest.", fill="#333333", font=f)

    img.save(OUT / "06_low_contrast.png")
    print("  Created 06_low_contrast.png")


# ── 7. Mixed font sizes ─────────────────────────────────────────────

def gen_mixed_sizes():
    img = Image.new("RGB", (800, 500), "#ffffff")
    d = ImageDraw.Draw(img)

    d.text((40, 20), "HEADLINE TEXT", fill="#000000", font=get_font(48))
    d.text((40, 85), "Subheadline with medium size", fill="#333333", font=get_font(28))
    d.text((40, 130), "Regular body text at normal reading size for comparison.", fill="#444444", font=get_font(18))
    d.text((40, 165), "Smaller caption text that might appear under images or figures.", fill="#666666", font=get_font(14))
    d.text((40, 195), "Very small fine print: Terms and conditions may apply. See store for details.", fill="#888888", font=get_font(11))

    # Tiny text
    d.text((40, 230), "TINY: The quick brown fox jumps over the lazy dog. 0123456789", fill="#999999", font=get_font(9))

    # Large decorative
    d.text((40, 280), "BIG", fill="#e0e0e0", font=get_font(120))

    # Overlaid smaller text
    d.text((60, 320), "Text layered on large background text", fill="#000000", font=get_font(16))

    img.save(OUT / "07_mixed_sizes.png")
    print("  Created 07_mixed_sizes.png")


# ── 8. Rotated / angled text ────────────────────────────────────────

def gen_rotated():
    img = Image.new("RGB", (600, 600), "#ffffff")
    f = get_font(24)

    # Create text at various angles
    angles = [0, 15, -10, 45, 90, -30]
    texts = ["Horizontal text", "Slight tilt", "Negative tilt",
             "Diagonal 45 deg", "Vertical text", "Angled -30"]
    positions = [(50, 30), (50, 100), (50, 180), (30, 250), (480, 50), (300, 350)]

    for text, angle, pos in zip(texts, angles, positions):
        txt_img = Image.new("RGBA", (400, 50), (255, 255, 255, 0))
        td = ImageDraw.Draw(txt_img)
        td.text((5, 5), text, fill="#000000", font=f)
        rotated = txt_img.rotate(angle, expand=True, fillcolor=(255, 255, 255, 0))
        img.paste(rotated, pos, rotated)

    img.save(OUT / "08_rotated.png")
    print("  Created 08_rotated.png")


# ── 9. Code / monospace ─────────────────────────────────────────────

def gen_code():
    img = Image.new("RGB", (700, 450), "#1e1e2e")
    d = ImageDraw.Draw(img)
    f = get_mono_font(16)

    code_lines = [
        ('def ', '#c678dd'), ('fibonacci', '#61afef'), ('(n):', '#abb2bf'),
    ]

    lines = [
        "def fibonacci(n):",
        "    if n <= 1:",
        "        return n",
        "    a, b = 0, 1",
        "    for _ in range(2, n + 1):",
        "        a, b = b, a + b",
        "    return b",
        "",
        "# Print first 10 numbers",
        "for i in range(10):",
        "    result = fibonacci(i)",
        '    print(f"F({i}) = {result}")',
        "",
        "# Output:",
        "# F(0) = 0, F(1) = 1, F(2) = 1",
        "# F(3) = 2, F(4) = 3, F(5) = 5",
    ]

    # Line numbers gutter
    y = 20
    for i, line in enumerate(lines, 1):
        d.text((15, y), f"{i:2d}", fill="#5c6370", font=f)
        d.line([(45, y), (45, y + 20)], fill="#3e4451", width=1)

        # Simple syntax coloring
        color = "#abb2bf"
        if line.startswith("#"):
            color = "#5c6370"
        elif line.strip().startswith(("def ", "for ", "if ", "return", "import")):
            color = "#c678dd"
        elif line.strip().startswith("print"):
            color = "#61afef"

        d.text((55, y), line, fill=color, font=f)
        y += 24

    img.save(OUT / "09_code.png")
    print("  Created 09_code.png")


# ── 10. Table / grid ────────────────────────────────────────────────

def gen_table():
    img = Image.new("RGB", (700, 400), "#ffffff")
    d = ImageDraw.Draw(img)
    f_h = get_font(16)
    f_body = get_font(14)

    d.text((40, 15), "Quarterly Revenue Report ($ millions)", fill="#111111", font=get_font(22))

    # Table structure
    cols = [40, 200, 320, 440, 560]
    headers = ["Company", "Q1", "Q2", "Q3", "Q4"]
    rows = [
        ["Acme Corp", "12.4", "14.1", "13.8", "16.2"],
        ["Beta Inc", "8.7", "9.3", "10.1", "11.5"],
        ["Gamma LLC", "22.1", "21.8", "23.4", "25.0"],
        ["Delta Co", "5.2", "6.0", "5.8", "7.1"],
        ["Epsilon Ltd", "15.9", "16.4", "17.2", "18.8"],
    ]

    # Header row
    y = 60
    d.rectangle([(35, y - 5), (660, y + 22)], fill="#e8e8e8")
    for col_x, header in zip(cols, headers):
        d.text((col_x, y), header, fill="#000000", font=f_h)

    # Grid lines
    d.line([(35, y - 5), (660, y - 5)], fill="#999999", width=1)
    d.line([(35, y + 22), (660, y + 22)], fill="#999999", width=1)

    # Data rows
    y = 90
    for row in rows:
        for col_x, val in zip(cols, row):
            d.text((col_x, y), val, fill="#333333", font=f_body)
        y += 30
        d.line([(35, y - 5), (660, y - 5)], fill="#dddddd", width=1)

    # Bottom border
    d.line([(35, y - 5), (660, y - 5)], fill="#999999", width=1)

    # Vertical column lines
    for x in cols:
        d.line([(x - 5, 55), (x - 5, y - 5)], fill="#dddddd", width=1)
    d.line([(660, 55), (660, y - 5)], fill="#dddddd", width=1)

    # Totals
    y += 5
    d.text((40, y), "Total", fill="#000000", font=f_h)
    totals = ["64.3", "67.6", "70.3", "78.6"]
    for col_x, val in zip(cols[1:], totals):
        d.text((col_x, y), val, fill="#000000", font=f_h)

    img.save(OUT / "10_table.png")
    print("  Created 10_table.png")


# ── 11. Colored background with white text ──────────────────────────

def gen_dark_bg():
    img = Image.new("RGB", (700, 400), "#1a1a2e")
    d = ImageDraw.Draw(img)

    # Gradient-like bands
    for y in range(0, 400, 2):
        r = int(26 + (y / 400) * 20)
        g = int(26 + (y / 400) * 10)
        b = int(46 + (y / 400) * 30)
        d.line([(0, y), (700, y)], fill=(r, g, b))

    f_big = get_font(36)
    f_med = get_font(20)
    f_sm = get_font(15)

    d.text((40, 30), "DARK MODE TEXT", fill="#ffffff", font=f_big)
    d.text((40, 85), "White text on dark background", fill="#e0e0e0", font=f_med)
    d.text((40, 125), "Various contrast levels to test OCR accuracy", fill="#b0b0b0", font=f_med)
    d.text((40, 175), "Accent color text for emphasis", fill="#58a6ff", font=f_med)
    d.text((40, 215), "Warning text in yellow tones", fill="#d29922", font=f_med)
    d.text((40, 255), "Success text in green", fill="#3fb950", font=f_med)
    d.text((40, 295), "Error text in red", fill="#f85149", font=f_med)
    d.text((40, 345), "Fine print on dark background - harder to read", fill="#666666", font=f_sm)

    img.save(OUT / "11_dark_background.png")
    print("  Created 11_dark_background.png")


# ── 12. Sign / poster ──────────────────────────────────────────────

def gen_sign():
    img = Image.new("RGB", (600, 400), "#2c5f2d")
    d = ImageDraw.Draw(img)

    # Border
    d.rectangle([(10, 10), (590, 390)], outline="#ffffff", width=4)
    d.rectangle([(18, 18), (582, 382)], outline="#ffffff", width=2)

    f_big = get_font(48)
    f_med = get_font(28)
    f_sm = get_font(18)

    d.text((100, 40), "WELCOME TO", fill="#ffffff", font=f_med)
    d.text((80, 90), "GREENFIELD", fill="#ffffff", font=f_big)
    d.text((175, 155), "PARK", fill="#ffffff", font=f_big)

    d.line([(60, 215), (540, 215)], fill="#ffffff", width=1)

    d.text((100, 230), "Open Daily: 6am - 9pm", fill="#e0e0e0", font=f_med)
    d.text((130, 280), "Dogs Welcome on Leash", fill="#e0e0e0", font=f_sm)
    d.text((130, 310), "No Littering - $500 Fine", fill="#e0e0e0", font=f_sm)
    d.text((100, 345), "Established 1952", fill="#b0c4b0", font=f_sm)

    img.save(OUT / "12_sign.png")
    print("  Created 12_sign.png")


# ── 13. Mixed languages (ASCII only for reliability) ────────────────

def gen_multilingual():
    img = Image.new("RGB", (700, 400), "#ffffff")
    d = ImageDraw.Draw(img)
    f = get_font(20)
    f_label = get_font(14)

    d.text((40, 20), "Multi-Language OCR Test", fill="#000000", font=get_font(28))
    d.line([(40, 58), (660, 58)], fill="#cccccc", width=1)

    entries = [
        ("English:", "The quick brown fox jumps over the lazy dog."),
        ("French:", "Le renard brun rapide saute par-dessus le chien."),
        ("German:", "Der schnelle braune Fuchs springt."),
        ("Spanish:", "El zorro marron rapido salta sobre el perro."),
        ("Italian:", "La volpe marrone veloce salta sopra il cane."),
        ("Portuguese:", "A raposa marrom rapida pula sobre o cachorro."),
    ]

    y = 75
    for label, text in entries:
        d.text((40, y), label, fill="#888888", font=f_label)
        d.text((140, y), text, fill="#222222", font=f)
        y += 45

    img.save(OUT / "13_multilingual.png")
    print("  Created 13_multilingual.png")


# ── 14. Dense small text (book page simulation) ────────────────────

def gen_book_page():
    img = Image.new("RGB", (600, 800), "#f8f4e8")
    d = ImageDraw.Draw(img)
    f = get_serif_font(14)
    f_h = get_font(12)

    d.text((250, 20), "Chapter 3", fill="#666666", font=get_font(11))
    d.line([(50, 38), (550, 38)], fill="#cccccc", width=1)

    paragraphs = [
        "It was the best of times, it was the worst of times, it was the age of wisdom, it was the age of foolishness, it was the epoch of belief, it was the epoch of incredulity.",
        "The sun had set behind the distant mountains, casting long purple shadows across the valley below. A cold wind began to stir the autumn leaves.",
        "She walked along the cobblestone path, her footsteps echoing in the narrow alley. The lamplighter had already begun his evening rounds.",
        "In the distance, the church bells tolled the hour. Seven chimes rang out across the quiet town, signaling the end of another day.",
        "The old bookshop on the corner had been there for as long as anyone could remember. Its windows glowed warmly in the fading light.",
        "He paused at the doorway, taking in the familiar scent of aged paper and leather bindings. Rows of books lined every wall, floor to ceiling.",
    ]

    y = 55
    for para in paragraphs:
        # Word-wrap
        words = para.split()
        line = ""
        for word in words:
            test = f"{line} {word}".strip()
            bbox = d.textbbox((0, 0), test, font=f)
            if bbox[2] > 500:
                d.text((50, y), line, fill="#222222", font=f)
                y += 20
                line = word
            else:
                line = test
        if line:
            d.text((50, y), line, fill="#222222", font=f)
            y += 20
        y += 12  # paragraph gap

    # Page number
    d.text((285, 760), "— 42 —", fill="#999999", font=f_h)

    img.save(OUT / "14_book_page.png")
    print("  Created 14_book_page.png")


# ── 15. Form / labels ──────────────────────────────────────────────

def gen_form():
    img = Image.new("RGB", (600, 500), "#ffffff")
    d = ImageDraw.Draw(img)
    f_title = get_font(22)
    f_label = get_font(14)
    f_value = get_font(16)

    d.text((40, 20), "Patient Registration Form", fill="#000000", font=f_title)
    d.line([(40, 52), (560, 52)], fill="#333333", width=2)

    fields = [
        ("First Name:", "John"),
        ("Last Name:", "Smith"),
        ("Date of Birth:", "1985-04-12"),
        ("Phone:", "(555) 867-5309"),
        ("Email:", "john.smith@email.com"),
        ("Address:", "742 Evergreen Terrace"),
        ("City:", "Springfield"),
        ("State:", "IL"),
        ("ZIP Code:", "62704"),
        ("Insurance ID:", "BC-2847593-A"),
    ]

    y = 70
    for label, value in fields:
        d.text((40, y), label, fill="#666666", font=f_label)
        d.text((180, y), value, fill="#000000", font=f_value)
        d.line([(180, y + 22), (500, y + 22)], fill="#cccccc", width=1)
        y += 38

    img.save(OUT / "15_form.png")
    print("  Created 15_form.png")


# ── Run all generators ──────────────────────────────────────────────

if __name__ == "__main__":
    print("Generating OCR test assets...")
    gen_simple_text()
    gen_article()
    gen_receipt()
    gen_columns()
    gen_handwriting()
    gen_low_contrast()
    gen_mixed_sizes()
    gen_rotated()
    gen_code()
    gen_table()
    gen_dark_bg()
    gen_sign()
    gen_multilingual()
    gen_book_page()
    gen_form()
    print(f"\nDone! {len(list(OUT.glob('*.png')))} images in {OUT}")
