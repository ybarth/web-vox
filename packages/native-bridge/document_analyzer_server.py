#!/usr/bin/env python3
"""
Document analyzer server for web-vox-pro.

Accepts text (plain, HTML, Markdown) and returns structured document
elements with type classification, positional info, and voice scheme
mappings for intelligent multi-voice reading.

Port: 21750

Usage:
    python3 document_analyzer_server.py [--port 21750] [--provider ollama|none] [--model llama3.1:8b]
"""

import argparse
import json
import re
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

# ── Configuration ─────────────────────────────────────────────────────

_provider = "none"  # "ollama" or "none" (rule-based only)
_model = "llama3.1:8b"
_ollama_url = "http://127.0.0.1:11434"

def _load_config():
    global _provider, _model
    config_path = Path(__file__).parent / "device_config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            doc = config.get("document_analyzer", {})
            _provider = doc.get("provider", _provider)
            _model = doc.get("model", _model)
        except Exception as e:
            print(f"  [doc-analyzer] Warning: failed to read device_config.json: {e}")


# ── Document element types ────────────────────────────────────────────

ELEMENT_TYPES = [
    "heading",          # section headings (h1-h6)
    "paragraph",        # body text
    "dialogue",         # quoted speech
    "dialogue_attr",    # dialogue attribution ("he said")
    "list_item",        # bullet/numbered list items
    "blockquote",       # block quotations
    "code_block",       # code/preformatted text
    "code_inline",      # inline code spans
    "emphasis",         # emphasized/italic text
    "strong",           # bold/strong text
    "link",             # hyperlinks
    "table_header",     # table header cells
    "table_cell",       # table body cells
    "footnote",         # footnotes/endnotes
    "aside",            # parenthetical/tangential content
    "separator",        # horizontal rules, scene breaks
    "title",            # document title
    "subtitle",         # document subtitle
    "caption",          # image/figure captions
    "metadata",         # author, date, etc.
]


# ── Default voice schemes ────────────────────────────────────────────

DEFAULT_VOICE_SCHEME = {
    "heading": {
        "rate": 0.9,
        "pitch": 1.1,
        "volume": 1.0,
        "pause_before_ms": 600,
        "pause_after_ms": 400,
        "voice_hint": "authoritative",
    },
    "paragraph": {
        "rate": 1.0,
        "pitch": 1.0,
        "volume": 1.0,
        "pause_before_ms": 200,
        "pause_after_ms": 200,
        "voice_hint": None,
    },
    "dialogue": {
        "rate": 1.0,
        "pitch": 1.05,
        "volume": 1.0,
        "pause_before_ms": 100,
        "pause_after_ms": 100,
        "voice_hint": "expressive",
    },
    "dialogue_attr": {
        "rate": 0.95,
        "pitch": 0.95,
        "volume": 0.85,
        "pause_before_ms": 0,
        "pause_after_ms": 100,
        "voice_hint": "neutral",
    },
    "list_item": {
        "rate": 1.0,
        "pitch": 1.0,
        "volume": 1.0,
        "pause_before_ms": 150,
        "pause_after_ms": 150,
        "voice_hint": None,
    },
    "blockquote": {
        "rate": 0.95,
        "pitch": 0.95,
        "volume": 0.9,
        "pause_before_ms": 300,
        "pause_after_ms": 300,
        "voice_hint": "reflective",
    },
    "code_block": {
        "rate": 0.85,
        "pitch": 0.9,
        "volume": 0.9,
        "pause_before_ms": 400,
        "pause_after_ms": 400,
        "voice_hint": "monotone",
    },
    "emphasis": {
        "rate": 0.95,
        "pitch": 1.05,
        "volume": 1.0,
        "pause_before_ms": 0,
        "pause_after_ms": 0,
        "voice_hint": None,
    },
    "strong": {
        "rate": 0.9,
        "pitch": 1.0,
        "volume": 1.1,
        "pause_before_ms": 0,
        "pause_after_ms": 0,
        "voice_hint": None,
    },
    "separator": {
        "rate": 1.0,
        "pitch": 1.0,
        "volume": 0.0,
        "pause_before_ms": 800,
        "pause_after_ms": 800,
        "voice_hint": None,
    },
    "title": {
        "rate": 0.85,
        "pitch": 1.15,
        "volume": 1.0,
        "pause_before_ms": 0,
        "pause_after_ms": 600,
        "voice_hint": "authoritative",
    },
    "subtitle": {
        "rate": 0.9,
        "pitch": 1.05,
        "volume": 0.95,
        "pause_before_ms": 0,
        "pause_after_ms": 400,
        "voice_hint": None,
    },
    "footnote": {
        "rate": 0.9,
        "pitch": 0.9,
        "volume": 0.8,
        "pause_before_ms": 300,
        "pause_after_ms": 300,
        "voice_hint": "quiet",
    },
    "caption": {
        "rate": 0.95,
        "pitch": 0.95,
        "volume": 0.85,
        "pause_before_ms": 200,
        "pause_after_ms": 200,
        "voice_hint": None,
    },
    "metadata": {
        "rate": 0.9,
        "pitch": 0.9,
        "volume": 0.8,
        "pause_before_ms": 200,
        "pause_after_ms": 200,
        "voice_hint": "neutral",
    },
}


# ── Rule-based plain text analyzer ───────────────────────────────────

# Patterns for structure detection
_HEADING_RE = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
_DIALOGUE_RE = re.compile(r'["\u201c]([^"\u201d]+)["\u201d]', re.DOTALL)
_DIALOGUE_ATTR_RE = re.compile(
    r'["\u201d]\s*,?\s*((?:he|she|they|it|I|we|[A-Z]\w+)\s+(?:said|asked|replied|whispered|shouted|exclaimed|murmured|muttered|called|cried|yelled|screamed|demanded|insisted|suggested|added|continued|began|concluded|answered|responded|stated|declared|announced|mentioned|noted|observed|remarked|commented|explained|warned|urged|pleaded|begged)\b[^.!?]*[.!?]?)',
    re.IGNORECASE
)
_LIST_RE = re.compile(r'^[\s]*(?:[-*+]|\d+[.)]) (.+)$', re.MULTILINE)
_HR_RE = re.compile(r'^[\s]*([-*_])\1{2,}[\s]*$', re.MULTILINE)
_CODE_BLOCK_RE = re.compile(r'```[\w]*\n(.*?)```', re.DOTALL)
_CODE_INLINE_RE = re.compile(r'`([^`]+)`')
_BLOCKQUOTE_RE = re.compile(r'^>\s*(.+)$', re.MULTILINE)
_STRONG_RE = re.compile(r'\*\*(.+?)\*\*|__(.+?)__')
_EMPHASIS_RE = re.compile(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)')
_LINK_RE = re.compile(r'\[([^\]]+)\]\([^)]+\)')

# Pure plain text heuristics (no markdown syntax)
_PLAIN_HEADING_RE = re.compile(r'^([A-Z][A-Z\s:,\-]+[A-Z])$', re.MULTILINE)
_PLAIN_CHAPTER_RE = re.compile(r'^(?:Chapter|CHAPTER|Part|PART|Section|SECTION)\s+[\dIVXLCDMivxlcdm]+\.?\s*.*$', re.MULTILINE)
_SCENE_BREAK_RE = re.compile(r'^\s*(?:\*\s*\*\s*\*|---+|___+|~~~+|\.\s*\.\s*\.)\s*$', re.MULTILINE)


def _detect_format(text: str) -> str:
    """Detect whether text is Markdown, HTML, or plain text."""
    if re.search(r'<(?:html|head|body|div|p|h[1-6]|span|br|ul|ol|li|table|a)\b', text, re.IGNORECASE):
        return "html"
    md_markers = 0
    if _HEADING_RE.search(text):
        md_markers += 1
    if _CODE_BLOCK_RE.search(text):
        md_markers += 1
    if re.search(r'\[.+\]\(.+\)', text):
        md_markers += 1
    if _STRONG_RE.search(text):
        md_markers += 1
    if md_markers >= 2:
        return "markdown"
    return "plain"


def _analyze_plain_text(text: str) -> list[dict]:
    """Rule-based analysis of plain text into document elements."""
    elements = []
    lines = text.split('\n')
    current_para = []
    current_offset = 0
    line_offsets = []

    # Pre-compute line offsets
    offset = 0
    for line in lines:
        line_offsets.append(offset)
        offset += len(line) + 1  # +1 for \n

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        line_start = line_offsets[i]

        # Empty line — flush paragraph
        if not stripped:
            if current_para:
                para_text = '\n'.join(current_para)
                para_start = line_offsets[i - len(current_para)]
                elements.extend(_split_paragraph_elements(para_text, para_start))
                current_para = []
            i += 1
            continue

        # Scene break / horizontal rule
        if _SCENE_BREAK_RE.match(line):
            if current_para:
                para_text = '\n'.join(current_para)
                para_start = line_offsets[i - len(current_para)]
                elements.extend(_split_paragraph_elements(para_text, para_start))
                current_para = []
            elements.append({
                "type": "separator",
                "text": stripped,
                "char_offset": line_start,
                "char_length": len(line),
                "level": 0,
            })
            i += 1
            continue

        # Chapter / section heading
        chapter_match = _PLAIN_CHAPTER_RE.match(stripped)
        if chapter_match:
            if current_para:
                para_text = '\n'.join(current_para)
                para_start = line_offsets[i - len(current_para)]
                elements.extend(_split_paragraph_elements(para_text, para_start))
                current_para = []
            elements.append({
                "type": "heading",
                "text": stripped,
                "char_offset": line_start + (len(line) - len(stripped)),
                "char_length": len(stripped),
                "level": 1,
            })
            i += 1
            continue

        # ALL-CAPS heading (at least 3 chars, not a single word like "I" or "OK")
        if (_PLAIN_HEADING_RE.match(stripped) and len(stripped) >= 4
                and not stripped.startswith(('--', '=='))):
            if current_para:
                para_text = '\n'.join(current_para)
                para_start = line_offsets[i - len(current_para)]
                elements.extend(_split_paragraph_elements(para_text, para_start))
                current_para = []
            elements.append({
                "type": "heading",
                "text": stripped,
                "char_offset": line_start + (len(line) - len(stripped)),
                "char_length": len(stripped),
                "level": 2,
            })
            i += 1
            continue

        # List items
        list_match = _LIST_RE.match(line)
        if list_match:
            if current_para:
                para_text = '\n'.join(current_para)
                para_start = line_offsets[i - len(current_para)]
                elements.extend(_split_paragraph_elements(para_text, para_start))
                current_para = []
            elements.append({
                "type": "list_item",
                "text": list_match.group(1),
                "char_offset": line_start + list_match.start(1),
                "char_length": len(list_match.group(1)),
                "level": 0,
            })
            i += 1
            continue

        # Accumulate paragraph
        current_para.append(line)
        i += 1

    # Flush remaining paragraph
    if current_para:
        para_text = '\n'.join(current_para)
        para_start = line_offsets[len(lines) - len(current_para)] if len(lines) >= len(current_para) else 0
        elements.extend(_split_paragraph_elements(para_text, para_start))

    return elements


def _split_paragraph_elements(text: str, base_offset: int) -> list[dict]:
    """Split a paragraph into sub-elements (dialogue, attribution, body text)."""
    elements = []

    # Find dialogue quotes
    dialogue_spans = []
    for m in _DIALOGUE_RE.finditer(text):
        dialogue_spans.append((m.start(), m.end(), m.group(1), "dialogue"))

    # Find dialogue attributions
    for m in _DIALOGUE_ATTR_RE.finditer(text):
        dialogue_spans.append((m.start(1), m.end(1), m.group(1).strip(), "dialogue_attr"))

    if not dialogue_spans:
        # No dialogue — entire thing is a paragraph
        elements.append({
            "type": "paragraph",
            "text": text,
            "char_offset": base_offset,
            "char_length": len(text),
            "level": 0,
        })
        return elements

    # Sort by position
    dialogue_spans.sort(key=lambda x: x[0])

    # Interleave regular text and dialogue
    pos = 0
    for start, end, content, dtype in dialogue_spans:
        if start > pos:
            prefix = text[pos:start].strip()
            if prefix:
                elements.append({
                    "type": "paragraph",
                    "text": prefix,
                    "char_offset": base_offset + pos,
                    "char_length": len(prefix),
                    "level": 0,
                })
        elements.append({
            "type": dtype,
            "text": content,
            "char_offset": base_offset + start,
            "char_length": end - start,
            "level": 0,
        })
        pos = end

    if pos < len(text):
        suffix = text[pos:].strip()
        if suffix:
            elements.append({
                "type": "paragraph",
                "text": suffix,
                "char_offset": base_offset + pos,
                "char_length": len(suffix),
                "level": 0,
            })

    return elements


# ── Markdown analyzer ────────────────────────────────────────────────

def _analyze_markdown(text: str) -> list[dict]:
    """Analyze markdown text into document elements."""
    elements = []
    remaining = text

    # Extract code blocks first (they shouldn't be parsed for other elements)
    code_blocks = []
    for m in _CODE_BLOCK_RE.finditer(text):
        code_blocks.append((m.start(), m.end(), m.group(1)))

    # Process line by line, skipping code block ranges
    lines = text.split('\n')
    offset = 0
    i = 0
    in_code_block = False
    code_block_content = []
    code_block_start = 0

    while i < len(lines):
        line = lines[i]
        line_start = offset
        stripped = line.strip()

        # Code block toggle
        if stripped.startswith('```'):
            if in_code_block:
                # End of code block
                cb_text = '\n'.join(code_block_content)
                elements.append({
                    "type": "code_block",
                    "text": cb_text,
                    "char_offset": code_block_start,
                    "char_length": line_start + len(line) - code_block_start,
                    "level": 0,
                })
                code_block_content = []
                in_code_block = False
            else:
                in_code_block = True
                code_block_start = line_start
            offset += len(line) + 1
            i += 1
            continue

        if in_code_block:
            code_block_content.append(line)
            offset += len(line) + 1
            i += 1
            continue

        # Empty line
        if not stripped:
            offset += len(line) + 1
            i += 1
            continue

        # Heading
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            elements.append({
                "type": "heading",
                "text": heading_text,
                "char_offset": line_start,
                "char_length": len(line),
                "level": level,
            })
            offset += len(line) + 1
            i += 1
            continue

        # Horizontal rule
        if _HR_RE.match(line):
            elements.append({
                "type": "separator",
                "text": stripped,
                "char_offset": line_start,
                "char_length": len(line),
                "level": 0,
            })
            offset += len(line) + 1
            i += 1
            continue

        # Blockquote
        bq_match = _BLOCKQUOTE_RE.match(line)
        if bq_match:
            elements.append({
                "type": "blockquote",
                "text": bq_match.group(1).strip(),
                "char_offset": line_start,
                "char_length": len(line),
                "level": 0,
            })
            offset += len(line) + 1
            i += 1
            continue

        # List item
        list_match = _LIST_RE.match(line)
        if list_match:
            elements.append({
                "type": "list_item",
                "text": list_match.group(1),
                "char_offset": line_start + list_match.start(1),
                "char_length": len(list_match.group(1)),
                "level": 0,
            })
            offset += len(line) + 1
            i += 1
            continue

        # Regular paragraph — collect consecutive non-blank, non-special lines
        para_lines = [line]
        offset += len(line) + 1
        i += 1
        while i < len(lines):
            next_line = lines[i]
            next_stripped = next_line.strip()
            if (not next_stripped or next_stripped.startswith('#') or
                next_stripped.startswith('```') or _HR_RE.match(next_line) or
                _LIST_RE.match(next_line) or _BLOCKQUOTE_RE.match(next_line)):
                break
            para_lines.append(next_line)
            offset += len(next_line) + 1
            i += 1

        para_text = ' '.join(l.strip() for l in para_lines)
        elements.extend(_split_paragraph_elements(para_text, line_start))
        continue

    return elements


# ── HTML analyzer ────────────────────────────────────────────────────

def _analyze_html(text: str) -> list[dict]:
    """Basic HTML structure extraction using regex (no external deps)."""
    elements = []

    # Strip common wrappers
    body_match = re.search(r'<body[^>]*>(.*?)</body>', text, re.DOTALL | re.IGNORECASE)
    content = body_match.group(1) if body_match else text

    tag_map = {
        'h1': ('heading', 1), 'h2': ('heading', 2), 'h3': ('heading', 3),
        'h4': ('heading', 4), 'h5': ('heading', 5), 'h6': ('heading', 6),
        'p': ('paragraph', 0),
        'li': ('list_item', 0),
        'blockquote': ('blockquote', 0),
        'pre': ('code_block', 0),
        'code': ('code_inline', 0),
        'em': ('emphasis', 0), 'i': ('emphasis', 0),
        'strong': ('strong', 0), 'b': ('strong', 0),
        'figcaption': ('caption', 0),
        'th': ('table_header', 0),
        'td': ('table_cell', 0),
        'hr': ('separator', 0),
    }

    for tag, (elem_type, level) in tag_map.items():
        if tag == 'hr':
            for m in re.finditer(r'<hr\s*/?\s*>', content, re.IGNORECASE):
                elements.append({
                    "type": "separator",
                    "text": "",
                    "char_offset": m.start(),
                    "char_length": m.end() - m.start(),
                    "level": 0,
                })
            continue

        pattern = rf'<{tag}[^>]*>(.*?)</{tag}>'
        for m in re.finditer(pattern, content, re.DOTALL | re.IGNORECASE):
            inner = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if inner:
                elements.append({
                    "type": elem_type,
                    "text": inner,
                    "char_offset": m.start(),
                    "char_length": m.end() - m.start(),
                    "level": level,
                })

    # Sort by position in document
    elements.sort(key=lambda e: e["char_offset"])
    return elements


# ── AI-powered analysis (Ollama) ─────────────────────────────────────

def _analyze_with_ai(text: str, rule_elements: list[dict]) -> list[dict]:
    """Enhance rule-based results with LLM classification."""
    if _provider != "ollama":
        return rule_elements

    try:
        import urllib.request
        prompt = _build_ai_prompt(text, rule_elements)
        payload = json.dumps({
            "model": _model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_predict": 4096},
        }).encode()

        req = urllib.request.Request(
            f"{_ollama_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            ai_data = json.loads(result.get("response", "{}"))
            return _merge_ai_results(rule_elements, ai_data)
    except Exception as e:
        print(f"  [doc-analyzer] AI enhancement failed, using rules only: {e}")
        return rule_elements


def _build_ai_prompt(text: str, elements: list[dict]) -> str:
    """Build prompt for LLM document structure analysis."""
    truncated = text[:3000] if len(text) > 3000 else text
    return f"""Analyze this text and classify each section's document structure type.

TEXT:
{truncated}

RULE-BASED ELEMENTS (verify and refine):
{json.dumps([{"type": e["type"], "text": e["text"][:80]} for e in elements[:20]], indent=2)}

Return a JSON object with:
{{
  "corrections": [
    {{"index": 0, "new_type": "dialogue", "confidence": 0.95}},
    ...
  ],
  "additional_elements": [
    {{"type": "aside", "text": "...", "char_offset": 100, "char_length": 50, "level": 0}},
    ...
  ],
  "document_metadata": {{
    "genre": "fiction|nonfiction|technical|poetry|drama",
    "has_dialogue": true,
    "estimated_reading_time_min": 5
  }}
}}

Valid types: {', '.join(ELEMENT_TYPES)}
Only include corrections where the rule-based type is wrong. Be conservative."""


def _merge_ai_results(rule_elements: list[dict], ai_data: dict) -> list[dict]:
    """Merge AI corrections into rule-based elements."""
    elements = list(rule_elements)

    corrections = ai_data.get("corrections", [])
    for corr in corrections:
        idx = corr.get("index", -1)
        new_type = corr.get("new_type", "")
        if 0 <= idx < len(elements) and new_type in ELEMENT_TYPES:
            confidence = corr.get("confidence", 0)
            if confidence >= 0.8:
                elements[idx]["type"] = new_type
                elements[idx]["ai_corrected"] = True

    additional = ai_data.get("additional_elements", [])
    for add in additional:
        if add.get("type") in ELEMENT_TYPES and add.get("text"):
            add["ai_added"] = True
            elements.append(add)

    # Re-sort by offset
    elements.sort(key=lambda e: e.get("char_offset", 0))
    return elements


# ── Voice scheme application ─────────────────────────────────────────

def _apply_voice_scheme(elements: list[dict], scheme: dict | None = None) -> list[dict]:
    """Apply voice scheme to each element."""
    vs = scheme or DEFAULT_VOICE_SCHEME
    for elem in elements:
        etype = elem["type"]
        mapping = vs.get(etype, vs.get("paragraph", {}))
        elem["voice"] = {
            "rate": mapping.get("rate", 1.0),
            "pitch": mapping.get("pitch", 1.0),
            "volume": mapping.get("volume", 1.0),
            "pause_before_ms": mapping.get("pause_before_ms", 0),
            "pause_after_ms": mapping.get("pause_after_ms", 0),
            "voice_hint": mapping.get("voice_hint"),
        }
    return elements


# ── Position tracking ────────────────────────────────────────────────

def _add_position_info(elements: list[dict], text: str) -> list[dict]:
    """Add sentence/paragraph/word position tracking."""
    # Count sentences, paragraphs
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    sentences = re.split(r'(?<=[.!?])\s+', text)
    total_words = len(text.split())

    para_idx = 0
    sent_idx = 0
    word_count = 0

    for elem in elements:
        elem_words = len(elem["text"].split())
        elem["position"] = {
            "word_offset": word_count,
            "word_count": elem_words,
            "total_words": total_words,
            "progress": round(word_count / total_words, 4) if total_words > 0 else 0,
        }
        word_count += elem_words

    return elements


# ── HTTP Handler ─────────────────────────────────────────────────────

class DocumentAnalyzerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default logging

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_cors_headers(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        self._send_cors_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._send_json({
                "status": "ok",
                "service": "document-analyzer",
                "provider": _provider,
                "model": _model if _provider != "none" else None,
                "element_types": ELEMENT_TYPES,
            })
        elif path == "/voice_scheme":
            self._send_json({
                "success": True,
                "scheme": DEFAULT_VOICE_SCHEME,
            })
        elif path == "/element_types":
            self._send_json({
                "success": True,
                "types": ELEMENT_TYPES,
            })
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""

        if path == "/analyze":
            self._handle_analyze(body)
        elif path == "/analyze_with_scheme":
            self._handle_analyze_with_scheme(body)
        else:
            self._send_json({"error": "Not found"}, 404)

    def _handle_analyze(self, body: bytes):
        t0 = time.time()
        try:
            req = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self._send_json({"success": False, "error": f"Invalid JSON: {e}"}, 400)
            return

        text = req.get("text", "")
        input_format = req.get("format", "auto")
        use_ai = req.get("use_ai", _provider != "none")
        custom_scheme = req.get("voice_scheme")

        if not text:
            self._send_json({"success": False, "error": "No text provided"}, 400)
            return

        # Detect or use specified format
        if input_format == "auto":
            input_format = _detect_format(text)

        print(f"  [doc-analyzer] Analyzing {len(text)} chars as {input_format}")

        # Run analysis
        if input_format == "html":
            elements = _analyze_html(text)
        elif input_format == "markdown":
            elements = _analyze_markdown(text)
        else:
            elements = _analyze_plain_text(text)

        # Optionally enhance with AI
        if use_ai and _provider != "none":
            elements = _analyze_with_ai(text, elements)

        # Apply voice scheme
        elements = _apply_voice_scheme(elements, custom_scheme)

        # Add position tracking
        elements = _add_position_info(elements, text)

        elapsed = time.time() - t0
        print(f"  [doc-analyzer] Found {len(elements)} elements in {elapsed:.3f}s")

        self._send_json({
            "success": True,
            "format": input_format,
            "elements": elements,
            "stats": {
                "total_elements": len(elements),
                "element_counts": _count_types(elements),
                "total_chars": len(text),
                "total_words": len(text.split()),
                "analysis_time_ms": round(elapsed * 1000, 1),
                "ai_enhanced": use_ai and _provider != "none",
            },
        })

    def _handle_analyze_with_scheme(self, body: bytes):
        """Analyze with a custom voice scheme overlaid."""
        try:
            req = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self._send_json({"success": False, "error": f"Invalid JSON: {e}"}, 400)
            return

        text = req.get("text", "")
        scheme = req.get("voice_scheme", DEFAULT_VOICE_SCHEME)

        if not text:
            self._send_json({"success": False, "error": "No text provided"}, 400)
            return

        input_format = _detect_format(text)
        if input_format == "html":
            elements = _analyze_html(text)
        elif input_format == "markdown":
            elements = _analyze_markdown(text)
        else:
            elements = _analyze_plain_text(text)

        elements = _apply_voice_scheme(elements, scheme)
        elements = _add_position_info(elements, text)

        self._send_json({
            "success": True,
            "format": input_format,
            "elements": elements,
            "scheme_applied": True,
        })


def _count_types(elements: list[dict]) -> dict:
    counts = {}
    for e in elements:
        t = e["type"]
        counts[t] = counts.get(t, 0) + 1
    return counts


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Document analyzer server")
    parser.add_argument("--port", type=int, default=21750)
    parser.add_argument("--provider", choices=["ollama", "none"], default=None)
    parser.add_argument("--model", type=str, default=None)
    args = parser.parse_args()

    _load_config()

    if args.provider:
        global _provider
        _provider = args.provider
    if args.model:
        global _model
        _model = args.model

    server = HTTPServer(("127.0.0.1", args.port), DocumentAnalyzerHandler)
    print(f"  [doc-analyzer] Document analyzer server running on http://127.0.0.1:{args.port}")
    print(f"  [doc-analyzer] Provider: {_provider}" + (f" ({_model})" if _provider != "none" else ""))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  [doc-analyzer] Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
