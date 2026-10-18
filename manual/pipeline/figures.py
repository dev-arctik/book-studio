# pipeline/figures.py
# Crops book illustrations out of the scanned pages for the clean PDF, using the picture boxes found by the OCR.
# Framed Deity photos: finds the photo (solid mid-grey area) and the decorative frame's border lines around it, and crops just inside them.
# Line drawings and unframed photos: trims the white margins; colour pictures keep their colour. Ornaments (drop caps, dividers, corner swirls) are filtered out by is_illustration().

import cv2
import numpy as np
import pypdfium2 as pdfium
from PIL import Image

CROP_DPI = 300  # sharp in print at the size the template places figures
MAX_EDGE = 1200  # px — over 300 dpi at the largest size the template prints a figure (10 cm); keeps the PDF small
DARK = 110  # grey level below which a pixel counts as frame line / ink
COLOUR_SHARE = 0.05  # a crop with at least this share of clearly saturated pixels is a colour picture (painting, photo plate)


def is_illustration(bbox, image_bbox) -> bool:
    """Real pictures only: drop caps and title dividers are tiny, corner swirls hug the very top of a page."""
    x0, y0, x1, y1 = bbox
    page_w, page_h = image_bbox[2], image_bbox[3]
    return (x1 - x0) * (y1 - y0) >= 0.05 * page_w * page_h and y0 >= 0.06 * page_h


def has_ink(figure: Image.Image) -> bool:
    """A photo or drawing has real dark tones; a faint background swirl or a blank verso page doesn't.
    Used where position can't tell them apart — e.g. a Deity photo starting at the very top of a front page."""
    return (np.array(figure.convert("L")) < 150).mean() >= 0.05


def _find_border(gray, rect, reach):
    """Inner edge of a decorative frame: the nearest dark line just outside rect on each side, or None if any side has none."""
    x0, y0, x1, y1 = rect
    h, w = gray.shape
    dark = gray < DARK

    def nearest(positions, line):
        return next((pos for pos in positions if line(pos).size and line(pos).mean() > 0.6), None)

    top = nearest(range(y0 + 3, max(-1, y0 - reach), -1), lambda y: dark[y, x0:x1])
    bottom = nearest(range(y1 - 3, min(h, y1 + reach)), lambda y: dark[y, x0:x1])
    left = nearest(range(x0 + 3, max(-1, x0 - reach), -1), lambda x: dark[y0:y1, x])
    right = nearest(range(x1 - 3, min(w, x1 + reach)), lambda x: dark[y0:y1, x])
    return None if None in (top, bottom, left, right) else (left, top, right, bottom)


def detect(gray) -> tuple[str, tuple[int, int, int, int]]:
    """('framed', box inside the frame) for a framed photo, else ('plain', box around the ink)."""
    h, w = gray.shape
    # Photo body = the largest solid patch of mid-grey tones; frames, drawings and text are pure black-on-white
    mid = ((gray > 35) & (gray < 225)).astype(np.uint8) * 255
    k = max(5, w // 60)
    mid = cv2.morphologyEx(mid, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))  # drop thin anti-aliased edges
    mid = cv2.morphologyEx(mid, cv2.MORPH_CLOSE, np.ones((k * 3, k * 3), np.uint8))  # fill the photo body
    n, _, stats, _ = cv2.connectedComponentsWithStats(mid)
    if n > 1:
        i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        x, y, bw, bh, area = stats[i]
        if area > 0.2 * w * h:
            # Only a photo with frame lines on all four sides counts as framed — shaded drawings have none
            border = _find_border(gray, (x, y, x + bw, y + bh), reach=max(12, w // 12))
            if border:
                left, top, right, bottom = border
                inset = max(6, (right - left) // 90)  # step past the frame line itself
                return "framed", (left + inset, top + inset, right - inset, bottom - inset)
    ys, xs = np.where(gray < 200)
    if not len(xs):
        return "plain", (0, 0, w, h)  # a very light picture (a pale poster, a faded photo): nothing to trim against
    return "plain", (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


def is_colour(region: Image.Image) -> bool:
    """Colour paintings and photo plates stay in colour; black-and-white pictures (grey scans have zero saturation) stay grey."""
    saturation = np.array(region.convert("HSV"))[..., 1]
    return (saturation > 64).mean() >= COLOUR_SHARE  # 64/255 ≈ 0.25: clearly coloured, not just a paper tint


def cover_image(pdf_path, height: int = 1600) -> Image.Image:
    """The book's front cover — page 1 of the original scan — in colour, about `height` pixels tall."""
    page = pdfium.PdfDocument(str(pdf_path))[0]
    return page.render(scale=height / page.get_size()[1]).to_pil().convert("RGB")


def crop_figure(pdf: pdfium.PdfDocument, page_no: int, bbox, image_bbox) -> Image.Image:
    """Render the page region at CROP_DPI and return the cleaned-up figure — in colour if the picture is coloured, else greyscale."""
    page = pdf[page_no - 1].render(scale=CROP_DPI / 72).to_pil().convert("RGB")
    scale = page.width / image_bbox[2]  # OCR boxes are in the OCR render's pixel space
    region = page.crop(tuple(int(v * scale) for v in bbox))
    _, (x0, y0, x1, y1) = detect(np.array(region.convert("L")))  # frame and margin detection work on grey tones
    figure = region.crop((x0, y0, x1, y1))
    figure = figure if is_colour(figure) else figure.convert("L")
    figure.thumbnail((MAX_EDGE, MAX_EDGE))
    return figure
