#!/usr/bin/env python3
"""Generate test images for the SDK test workbench OCR tests.

Run from the test-engines/sdk/ directory:
    python3 generate_test_images.py

Requires: Pillow (pip install Pillow)
"""
import os
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = os.path.join(os.path.dirname(__file__), "test-images")
os.makedirs(OUT_DIR, exist_ok=True)

# Try to find a decent font
FONT_PATHS = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/SFNSMono.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
MONO_PATHS = [
    "/System/Library/Fonts/SFNSMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Courier.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]

def find_font(paths, size=24):
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()

def find_mono(size=18):
    return find_font(MONO_PATHS, size)


def img_clean_text():
    """01: Clean printed text — ideal OCR conditions."""
    img = Image.new("RGB", (600, 200), "#FFFFFF")
    d = ImageDraw.Draw(img)
    font = find_font(FONT_PATHS, 28)
    d.text((30, 30), "The quick brown fox jumps", fill="#000000", font=font)
    d.text((30, 70), "over the lazy dog.", fill="#000000", font=font)
    font_sm = find_font(FONT_PATHS, 20)
    d.text((30, 130), "Pack my box with five dozen liquor jugs.", fill="#333333", font=font_sm)
    img.save(os.path.join(OUT_DIR, "01_clean_text.png"))
    print("  01_clean_text.png")


def img_multi_paragraph():
    """02: Multi-paragraph article text."""
    img = Image.new("RGB", (700, 350), "#FFFFF8")
    d = ImageDraw.Draw(img)
    title_font = find_font(FONT_PATHS, 30)
    body_font = find_font(FONT_PATHS, 18)

    d.text((40, 20), "Breaking News", fill="#000000", font=title_font)
    d.line([(40, 58), (660, 58)], fill="#CCCCCC", width=1)

    lines = [
        "Scientists at the National Laboratory announced a major",
        "breakthrough in renewable energy storage today. The new",
        "technology could revolutionize how cities manage their",
        "power grids during peak demand periods.",
        "",
        "\"This is a game-changer,\" said Dr. Maria Santos, the",
        "lead researcher. \"We can now store ten times more energy",
        "at a fraction of the cost.\"",
    ]
    y = 75
    for line in lines:
        if line:
            d.text((40, y), line, fill="#222222", font=body_font)
        y += 28
    img.save(os.path.join(OUT_DIR, "02_multi_paragraph.png"))
    print("  02_multi_paragraph.png")


def img_receipt():
    """03: Receipt / structured data."""
    img = Image.new("RGB", (400, 500), "#FAFAFA")
    d = ImageDraw.Draw(img)
    mono = find_mono(16)
    title = find_font(FONT_PATHS, 22)

    d.text((120, 20), "COFFEE SHOP", fill="#000000", font=title)
    d.text((130, 50), "Receipt #4827", fill="#666666", font=mono)
    d.line([(30, 80), (370, 80)], fill="#000000", width=1)

    items = [
        ("Cappuccino (large)    ", " $5.50"),
        ("Blueberry Muffin      ", " $3.75"),
        ("Avocado Toast         ", " $8.95"),
        ("Orange Juice          ", " $4.25"),
    ]
    y = 100
    for name, price in items:
        d.text((30, y), name, fill="#000000", font=mono)
        d.text((300, y), price, fill="#000000", font=mono)
        y += 30

    d.line([(30, y + 5), (370, y + 5)], fill="#000000", width=1)
    y += 20
    d.text((30, y), "Subtotal              ", fill="#000000", font=mono)
    d.text((300, y), "$22.45", fill="#000000", font=mono)
    y += 30
    d.text((30, y), "Tax (8.5%)            ", fill="#000000", font=mono)
    d.text((300, y), " $1.91", fill="#000000", font=mono)
    y += 30
    d.line([(30, y + 5), (370, y + 5)], fill="#000000", width=2)
    y += 20
    total_font = find_font(FONT_PATHS, 22)
    d.text((30, y), "TOTAL", fill="#000000", font=total_font)
    d.text((280, y), "$24.36", fill="#000000", font=total_font)
    y += 50
    d.text((100, y), "Thank you!", fill="#666666", font=mono)
    img.save(os.path.join(OUT_DIR, "03_receipt.png"))
    print("  03_receipt.png")


def img_two_columns():
    """04: Two-column layout."""
    img = Image.new("RGB", (800, 350), "#FFFFFF")
    d = ImageDraw.Draw(img)
    font = find_font(FONT_PATHS, 16)
    title = find_font(FONT_PATHS, 24)

    d.text((30, 15), "Column Layout Test", fill="#000000", font=title)
    d.line([(30, 48), (770, 48)], fill="#999999", width=1)

    # Column 1
    col1 = [
        "The first column contains",
        "introductory material about",
        "the topic at hand. It sets",
        "the stage for the detailed",
        "analysis that follows in",
        "the adjacent column.",
    ]
    # Column 2
    col2 = [
        "The second column provides",
        "supporting evidence and",
        "technical details. Numbers",
        "and data are presented in",
        "a clear, structured format",
        "for easy reference.",
    ]

    # Divider
    d.line([(400, 55), (400, 320)], fill="#CCCCCC", width=1)

    y = 65
    for line in col1:
        d.text((30, y), line, fill="#222222", font=font)
        y += 26
    y = 65
    for line in col2:
        d.text((420, y), line, fill="#222222", font=font)
        y += 26
    img.save(os.path.join(OUT_DIR, "04_two_columns.png"))
    print("  04_two_columns.png")


def img_mixed_sizes():
    """05: Mixed font sizes — headline, subhead, body, caption."""
    img = Image.new("RGB", (700, 350), "#FFFFFF")
    d = ImageDraw.Draw(img)

    h1 = find_font(FONT_PATHS, 40)
    h2 = find_font(FONT_PATHS, 26)
    body = find_font(FONT_PATHS, 18)
    caption = find_font(FONT_PATHS, 12)

    d.text((30, 20), "Main Headline", fill="#000000", font=h1)
    d.text((30, 80), "Secondary Heading", fill="#444444", font=h2)
    d.text((30, 130), "This is the body text of the article. It contains", fill="#222222", font=body)
    d.text((30, 158), "important information presented in a readable size.", fill="#222222", font=body)
    d.text((30, 210), "Another paragraph follows with additional context", fill="#222222", font=body)
    d.text((30, 238), "and supporting details for the reader.", fill="#222222", font=body)
    d.text((30, 290), "Figure 1: Caption text appears in a smaller font, providing context for visuals above.", fill="#888888", font=caption)
    d.text((30, 310), "Source: Annual Report 2026, National Laboratory. All rights reserved.", fill="#AAAAAA", font=caption)
    img.save(os.path.join(OUT_DIR, "05_mixed_sizes.png"))
    print("  05_mixed_sizes.png")


def img_dark_bg():
    """06: Light text on dark background."""
    img = Image.new("RGB", (600, 250), "#1A1A2E")
    d = ImageDraw.Draw(img)
    font = find_font(FONT_PATHS, 24)
    small = find_font(FONT_PATHS, 16)

    d.text((30, 30), "Light on Dark", fill="#E6EDF3", font=font)
    d.text((30, 75), "This text is white on a dark navy", fill="#C9D1D9", font=small)
    d.text((30, 100), "background. OCR systems sometimes", fill="#C9D1D9", font=small)
    d.text((30, 125), "struggle with inverted contrast.", fill="#C9D1D9", font=small)
    d.text((30, 175), "Accent color text for variety.", fill="#58A6FF", font=small)
    d.text((30, 200), "Warning: low contrast test.", fill="#D29922", font=small)
    img.save(os.path.join(OUT_DIR, "06_dark_background.png"))
    print("  06_dark_background.png")


def img_code_block():
    """07: Code block with syntax-like coloring."""
    img = Image.new("RGB", (650, 300), "#0D1117")
    d = ImageDraw.Draw(img)
    mono = find_mono(16)

    lines = [
        ("#8B949E", "// SDK Quick Start Example"),
        ("#FF7B72", "import"),
        ("#C9D1D9", " { WebVox, NativeBridgeEngine }"),
        ("#FF7B72", " from "),
        ("#A5D6FF", "'@web-vox/core'"),
        ("#C9D1D9", ";"),
        ("", ""),
        ("#FF7B72", "const "),
        ("#D2A8FF", "engine"),
        ("#C9D1D9", " = new NativeBridgeEngine();"),
        ("#FF7B72", "await "),
        ("#D2A8FF", "engine"),
        ("#C9D1D9", ".initialize();"),
    ]

    # Simplified: render as full lines
    code_lines = [
        ("// SDK Quick Start Example", "#8B949E"),
        ("import { WebVox } from '@web-vox/core';", "#C9D1D9"),
        ("", None),
        ("const engine = new NativeBridgeEngine();", "#C9D1D9"),
        ("await engine.initialize();", "#C9D1D9"),
        ("", None),
        ("const result = await engine.synthesize(", "#C9D1D9"),
        ('  "Hello, world!",', "#A5D6FF"),
        ("  { rate: 1.0, alignment: 'word' }", "#C9D1D9"),
        (");", "#C9D1D9"),
    ]

    y = 20
    for i, (text, color) in enumerate(code_lines):
        if text:
            num = f"{i+1:2d} "
            d.text((15, y), num, fill="#484F58", font=mono)
            d.text((50, y), text, fill=color, font=mono)
        y += 24

    img.save(os.path.join(OUT_DIR, "07_code_block.png"))
    print("  07_code_block.png")


def img_table():
    """08: Simple data table."""
    img = Image.new("RGB", (600, 280), "#FFFFFF")
    d = ImageDraw.Draw(img)
    font = find_font(FONT_PATHS, 16)
    header_font = find_font(FONT_PATHS, 16)

    headers = ["Engine", "Latency", "Quality", "Status"]
    rows = [
        ["macOS AVSpeech", "45ms", "Good", "Active"],
        ["Kokoro", "320ms", "Excellent", "Active"],
        ["Piper", "180ms", "Good", "Active"],
        ["Coqui XTTS", "890ms", "Excellent", "Standby"],
        ["espeak-ng", "15ms", "Fair", "Active"],
    ]

    col_widths = [160, 100, 100, 100]
    x_start = 30
    y = 20

    # Header
    x = x_start
    for i, h in enumerate(headers):
        d.text((x, y), h, fill="#000000", font=header_font)
        x += col_widths[i]
    y += 28
    d.line([(x_start, y), (x_start + sum(col_widths), y)], fill="#000000", width=2)
    y += 8

    # Rows
    for row in rows:
        x = x_start
        for i, cell in enumerate(row):
            d.text((x, y), cell, fill="#333333", font=font)
            x += col_widths[i]
        y += 30
        d.line([(x_start, y - 4), (x_start + sum(col_widths), y - 4)], fill="#E0E0E0", width=1)

    img.save(os.path.join(OUT_DIR, "08_table.png"))
    print("  08_table.png")


def img_multilingual():
    """09: Multiple languages."""
    img = Image.new("RGB", (600, 300), "#FFFFFF")
    d = ImageDraw.Draw(img)
    font = find_font(FONT_PATHS, 20)
    label = find_font(FONT_PATHS, 14)

    texts = [
        ("English", "The quick brown fox jumps over the lazy dog."),
        ("French", "Le renard brun rapide saute par-dessus le chien."),
        ("German", "Der schnelle braune Fuchs springt über den Hund."),
        ("Spanish", "El rápido zorro marrón salta sobre el perro."),
        ("Italian", "La rapida volpe marrone salta sopra il cane."),
    ]

    y = 20
    for lang, text in texts:
        d.text((30, y), f"[{lang}]", fill="#888888", font=label)
        d.text((30, y + 18), text, fill="#222222", font=font)
        y += 52

    img.save(os.path.join(OUT_DIR, "09_multilingual.png"))
    print("  09_multilingual.png")


def img_noisy():
    """10: Text with background noise / low contrast."""
    import random
    img = Image.new("RGB", (500, 180), "#E8E4DC")
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

    font = find_font(FONT_PATHS, 22)
    d.text((30, 30), "Low contrast with noise", fill="#8A8478", font=font)
    d.text((30, 70), "Can the OCR read this text?", fill="#7A7468", font=font)
    d.text((30, 110), "Challenging conditions test.", fill="#6A6458", font=font)
    img.save(os.path.join(OUT_DIR, "10_noisy.png"))
    print("  10_noisy.png")


def img_form():
    """11: Form with labels and values."""
    img = Image.new("RGB", (550, 350), "#FFFFFF")
    d = ImageDraw.Draw(img)
    label_font = find_font(FONT_PATHS, 14)
    value_font = find_font(FONT_PATHS, 18)
    title_font = find_font(FONT_PATHS, 22)

    d.text((30, 15), "Registration Form", fill="#000000", font=title_font)
    d.line([(30, 48), (520, 48)], fill="#CCCCCC", width=1)

    fields = [
        ("Full Name", "Jane Elizabeth Smith"),
        ("Email Address", "jane.smith@example.com"),
        ("Phone Number", "(555) 234-5678"),
        ("Date of Birth", "April 15, 1992"),
        ("Organization", "Acme Research Labs"),
    ]

    y = 65
    for lbl, val in fields:
        d.text((30, y), lbl, fill="#888888", font=label_font)
        d.text((30, y + 18), val, fill="#222222", font=value_font)
        d.line([(30, y + 44), (520, y + 44)], fill="#E0E0E0", width=1)
        y += 55

    img.save(os.path.join(OUT_DIR, "11_form.png"))
    print("  11_form.png")


def img_sign():
    """12: Large display / sign text."""
    img = Image.new("RGB", (700, 250), "#1B4332")
    d = ImageDraw.Draw(img)

    big = find_font(FONT_PATHS, 52)
    sub = find_font(FONT_PATHS, 24)

    # Border
    d.rectangle([(10, 10), (690, 240)], outline="#FFD700", width=3)

    d.text((50, 40), "WELCOME", fill="#FFFFFF", font=big)
    d.text((50, 110), "Web-Vox Pro SDK", fill="#FFD700", font=sub)
    d.text((50, 150), "Test Workbench v0.1.0", fill="#B7E4C7", font=sub)
    d.text((50, 195), "Port 5400", fill="#95D5B2", font=find_font(FONT_PATHS, 18))
    img.save(os.path.join(OUT_DIR, "12_sign.png"))
    print("  12_sign.png")


if __name__ == "__main__":
    print("Generating SDK test images...")
    img_clean_text()
    img_multi_paragraph()
    img_receipt()
    img_two_columns()
    img_mixed_sizes()
    img_dark_bg()
    img_code_block()
    img_table()
    img_multilingual()
    img_noisy()
    img_form()
    img_sign()
    print(f"\nDone! {len(os.listdir(OUT_DIR))} images in {OUT_DIR}/")
