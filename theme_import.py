import json
from urllib.parse import parse_qs, urlparse

try:
    import cv2
    import numpy as np
except Exception:
    cv2 = None
    np = None

from PIL import ImageColor

import render

COLOR_MAP = {
    "bg": "bg",
    "panel": "panel",
    "ink": "ink",
    "on-ink": "on_ink",
    "muted": "muted",
    "line": "line",
    "edge": "edge",
    "outline": "outline",
    "chip-building": "building",
    "chip-cabinet": "cabinet",
    "today": "today"
}


def decode_qr(data):
    if cv2 is None or np is None:
        return ""
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return ""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    variants = [image, gray]
    height, width = image.shape[:2]
    if max(height, width) < 1200:
        scaled = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
        variants.append(scaled)
        _, threshold = cv2.threshold(scaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append(threshold)
    detectors = [cv2.QRCodeDetector()]
    if hasattr(cv2, "QRCodeDetectorAruco"):
        try:
            detectors.append(cv2.QRCodeDetectorAruco())
        except cv2.error:
            pass
    for detector in detectors:
        for variant in variants:
            try:
                text, _, _ = detector.detectAndDecode(variant)
            except cv2.error:
                text = ""
            if text:
                return text.strip()
    return ""


def parse_style(text):
    source = str(text or "").strip()
    if not source:
        return None
    payload = ""
    if source.startswith("{"):
        payload = source
    else:
        try:
            query = parse_qs(urlparse(source).query)
            payload = (query.get("style") or [""])[0]
        except ValueError:
            payload = ""
    if not payload:
        return None
    try:
        style = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(style, dict):
        return None
    colors = style.get("colors")
    if not isinstance(colors, dict):
        return None
    if not any(isinstance(colors.get(mode), dict) for mode in ("light", "dark")):
        return None
    return style


def normalize_color(value, fallback):
    try:
        rgb = ImageColor.getrgb(str(value))
    except (ValueError, TypeError):
        return fallback
    if len(rgb) == 4:
        rgb = rgb[:3]
    return "#%02x%02x%02x" % tuple(rgb)


def image_url(value):
    source = str(value or "").strip()
    if source.startswith("//"):
        source = "https:" + source
    if urlparse(source).scheme in ("http", "https"):
        return source
    return ""


def fix_contrast(palette):
    bg = render.relative_luminance(palette["bg"])
    ink = render.relative_luminance(palette["ink"])
    if abs(bg - ink) < 0.2:
        palette["ink"] = "#e7e9ee" if bg < 0.5 else "#111318"
    ink = render.relative_luminance(palette["ink"])
    on_ink = render.relative_luminance(palette["on_ink"])
    if abs(ink - on_ink) < 0.25:
        palette["on_ink"] = "#111318" if ink > 0.5 else "#ffffff"
    return palette


def to_theme(style):
    result = {"label": "Своя"}
    for mode in ("light", "dark"):
        base = dict(render.DEFAULT)
        if mode == "dark":
            base.update(render.DARK_THEMES["default"])
        source = (style.get("colors") or {}).get(mode)
        if isinstance(source, dict):
            for site_key, bot_key in COLOR_MAP.items():
                if site_key not in source:
                    continue
                raw = source[site_key]
                if bot_key == "bg" and image_url(raw):
                    base["bgImage"] = image_url(raw)
                    continue
                if bot_key == "panel" and image_url(raw):
                    base["panelImage"] = image_url(raw)
                    continue
                base[bot_key] = normalize_color(raw, base[bot_key])
            if "panel" not in source:
                base["panel"] = base["bg"]
        try:
            radius = int(style.get("radius") or 0)
        except (TypeError, ValueError):
            radius = 0
        base["radius"] = max(0, min(28, radius))
        base["shadow"] = style.get("shadow") is not False
        result[mode] = fix_contrast(base)
    result["bgImage"] = image_url(style.get("bgImage"))
    return result


def theme_from_qr(data):
    text = decode_qr(data)
    if not text:
        return None
    style = parse_style(text)
    if not style:
        return None
    return to_theme(style)
