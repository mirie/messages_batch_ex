"""Draw invoices as scanned page images, with no text layer in the PDF.

Claude receives each PDF page as an image plus the page's extracted text. The
documents built here put only a picture on the page, so the picture is all
Claude can read. Small digits that are easy to confuse then become real
reading mistakes instead of something the text layer quietly fixes.

How a scanned document is made:

    draw the page sharply      make it look scanned            save it
    (Pillow, 200 dpi)    -->   (shrink, tilt, blur, noise) --> (one image per
                                                                PDF page)

Every random choice comes from the generator's shared random.Random, so the
output is byte-identical on every run.
"""

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

PAGE_WIDTH_POINTS, PAGE_HEIGHT_POINTS = letter
RENDER_DPI = 200
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
BLUE_INK = (25, 55, 170)


def scan_money(amount: float, currency: str) -> str:
    """Format an amount for a scanned page, like $38.83 or EUR 81.38.

    Pillow's built-in font has a dollar sign but no pound or euro sign, so the
    other currencies are written as their code.
    """
    if currency == "USD":
        return f"${amount:,.2f}"
    return f"{currency} {amount:,.2f}"


# Each handwritten digit is one or more pen strokes in a unit box.
# x runs left to right and y runs bottom to top, both from 0 to 1.
HAND_STROKES = {
    "0": [[(0.5, 1), (0.15, 0.8), (0.1, 0.3), (0.5, 0), (0.9, 0.3), (0.85, 0.8), (0.5, 1)]],
    "1": [[(0.3, 0.8), (0.55, 1), (0.5, 0)]],
    "2": [[(0.1, 0.8), (0.4, 1), (0.8, 0.85), (0.75, 0.55), (0.1, 0), (0.9, 0.02)]],
    "3": [[(0.1, 0.9), (0.6, 1), (0.8, 0.8), (0.45, 0.55), (0.85, 0.3), (0.6, 0), (0.1, 0.1)]],
    "4": [[(0.6, 1), (0.1, 0.35), (0.9, 0.35)], [(0.65, 0.7), (0.6, 0)]],
    "5": [[(0.85, 1), (0.25, 1), (0.2, 0.55), (0.7, 0.6), (0.85, 0.3), (0.55, 0), (0.1, 0.1)]],
    "6": [[(0.75, 1), (0.3, 0.7), (0.15, 0.3), (0.4, 0), (0.8, 0.2), (0.7, 0.5), (0.2, 0.4)]],
    "7": [[(0.1, 1), (0.9, 1), (0.4, 0)]],
    "8": [
        [
            (0.5, 0.55),
            (0.15, 0.8),
            (0.5, 1),
            (0.85, 0.8),
            (0.5, 0.55),
            (0.1, 0.25),
            (0.5, 0),
            (0.9, 0.25),
            (0.5, 0.55),
        ]
    ],
    "9": [[(0.85, 0.7), (0.5, 1), (0.15, 0.75), (0.45, 0.5), (0.85, 0.7), (0.75, 0)]],
}


class ScanPage:
    """Hold a white letter-size page image and draw on it.

    Positions are given in PDF points from the bottom-left corner, the same
    way the reportlab layouts in layouts.py work, so the two read alike.
    """

    def __init__(self, dpi: int = RENDER_DPI):
        self.dpi = dpi
        size = (self.to_pixels(PAGE_WIDTH_POINTS), self.to_pixels(PAGE_HEIGHT_POINTS))
        self.image = Image.new("RGB", size, WHITE)
        self.draw = ImageDraw.Draw(self.image)

    def to_pixels(self, points: float) -> int:
        """Convert a length in points (1/72 inch) to pixels at this page's resolution."""
        return round(points * self.dpi / 72)

    def position(self, x: float, y: float) -> tuple[int, int]:
        """Convert a point position measured from the bottom left into pixels from the top left."""
        return self.to_pixels(x), self.to_pixels(PAGE_HEIGHT_POINTS - y)

    def text(self, x, y, text, size=10, *, bold=False, align="left", ink=BLACK):
        """Draw one line of text with its baseline at y.

        The align value says whether x is the text's left edge, right edge or centre.
        Return the text's bounding box in pixels.
        """
        font = ImageFont.load_default(size=self.to_pixels(size))
        anchor = {"left": "ls", "right": "rs", "center": "ms"}[align]
        stroke = max(1, self.to_pixels(size) // 25) if bold else 0
        options = {"font": font, "anchor": anchor, "stroke_width": stroke}
        self.draw.text(self.position(x, y), text, fill=ink, stroke_fill=ink, **options)
        return self.draw.textbbox(self.position(x, y), text, **options)

    def line(self, x0, y0, x1, y1, width=1.0, ink=BLACK):
        """Draw a straight line between two points."""
        self.draw.line(
            [self.position(x0, y0), self.position(x1, y1)],
            fill=ink,
            width=max(1, self.to_pixels(width)),
        )

    def handwrite(self, x, y, digits, height, rng: random.Random, ink=BLUE_INK):
        """Write digits by hand, starting at x with their bottom at y.

        Every pen point wobbles a little and the writing leans right, so no two
        digits look exactly alike.
        """
        digit_width = height * 0.6
        slant = 0.2
        pen_width = max(2, self.to_pixels(height * 0.09))
        for index, digit in enumerate(digits):
            left = x + index * digit_width * 1.15
            for stroke in HAND_STROKES[digit]:
                pen_points = []
                for unit_x, unit_y in stroke:
                    wobble_x = rng.uniform(-0.06, 0.06)
                    wobble_y = rng.uniform(-0.05, 0.05)
                    point_x = left + (unit_x + wobble_x + slant * unit_y) * digit_width
                    point_y = y + (unit_y + wobble_y) * height
                    pen_points.append(self.position(point_x, point_y))
                self.draw.line(pen_points, fill=ink, width=pen_width, joint="curve")

    def cross_out_and_rewrite(self, box, digits, rng: random.Random, ink=BLUE_INK):
        """Strike through the printed text in a pixel box and handwrite digits to its left."""
        left, top, right, bottom = box
        middle = (top + bottom) / 2
        pen_width = max(2, self.to_pixels(1.2))
        self.draw.line([(left - 6, middle + 4), (right + 6, middle - 4)], fill=ink, width=pen_width)
        baseline_points = PAGE_HEIGHT_POINTS - bottom * 72 / self.dpi
        left_points = left * 72 / self.dpi
        self.handwrite(left_points - 26, baseline_points - 1, digits, 14, rng, ink)

    def stain(self, x, y, width, height, darkness=110):
        """Lay a grey, coffee-like blot over an area, centred on (x, y)."""
        blot = Image.new("L", self.image.size, 0)
        blot_draw = ImageDraw.Draw(blot)
        left, top = self.position(x - width / 2, y + height / 2)
        right, bottom = self.position(x + width / 2, y - height / 2)
        blot_draw.ellipse([left, top, right, bottom], fill=darkness)
        blot = blot.filter(ImageFilter.GaussianBlur(self.to_pixels(4)))
        grey = Image.new("RGB", self.image.size, (120, 95, 70))
        self.image = Image.composite(grey, self.image, blot)
        self.draw = ImageDraw.Draw(self.image)


def draw_scanned_invoice(
    page: ScanPage,
    inv: dict,
    *,
    item_size: float = 10,
    total_size: float = 14,
    show_amounts: bool = True,
    printed_quantities: dict[int, int] | None = None,
) -> list[tuple[int, int, int, int]]:
    """Draw a plain, classic-style invoice onto the page.

    Set show_amounts to False to leave out the line-amount column, so a misread
    quantity cannot be checked against its row. Use printed_quantities to print
    a different quantity on some rows than the one in inv, for example the old
    value of a handwritten correction.

    Return the pixel box of each row's quantity, so a caller can strike it through.
    """
    currency = inv["currency"]
    printed_quantities = printed_quantities or {}
    page.text(50, 740, inv["vendor"], 18, bold=True)
    for index, address_line in enumerate(inv["vendor_address"]):
        page.text(50, 724 - index * 12, address_line, 9)
    page.text(562, 738, "INVOICE", 24, bold=True, align="right")

    details = [("Invoice No.", inv["invoice_no"]), ("Issue Date", inv["issue_date"].isoformat())]
    if inv["due_date"]:
        details.append(("Due Date", inv["due_date"].isoformat()))
    for index, (label, value) in enumerate(details):
        page.text(370, 700 - index * 15, f"{label}:", 10)
        page.text(562, 700 - index * 15, value, 10, align="right")

    page.text(50, 660, "Bill To", 10, bold=True)
    page.text(50, 645, inv["customer_name"], 10)
    page.text(50, 630, inv["customer_email"], 10)

    quantity_right = 380 if show_amounts else 460
    price_right = 470 if show_amounts else 562
    row_y = 590
    page.text(50, row_y, "Description", 10, bold=True)
    page.text(quantity_right, row_y, "Qty", 10, bold=True, align="right")
    page.text(price_right, row_y, "Unit Price", 10, bold=True, align="right")
    if show_amounts:
        page.text(562, row_y, "Amount", 10, bold=True, align="right")
    page.line(50, row_y - 6, 562, row_y - 6)

    quantity_boxes = []
    for index, item in enumerate(inv["line_items"]):
        row_y -= item_size * 2.2
        quantity = printed_quantities.get(index, item["quantity"])
        page.text(50, row_y, item["description"], item_size)
        box = page.text(quantity_right, row_y, str(quantity), item_size, align="right")
        quantity_boxes.append(box)
        page.text(
            price_right, row_y, scan_money(item["unit_price"], currency), item_size, align="right"
        )
        if show_amounts:
            amount = scan_money(item["quantity"] * item["unit_price"], currency)
            page.text(562, row_y, amount, item_size, align="right")
    page.line(50, row_y - 10, 562, row_y - 10)
    total_y = row_y - 10 - total_size * 2
    page.text(370, total_y, "Total", total_size, bold=True)
    page.text(
        562, total_y, scan_money(inv["total"], currency), total_size, bold=True, align="right"
    )
    page.text(50, 60, "Thank you for your business.", 8)
    return quantity_boxes


def make_scanned(
    page: ScanPage,
    rng: random.Random,
    *,
    scan_dpi: int,
    tilt_degrees: float,
    blur_radius: float,
    noise: float,
    threshold: int | None = None,
) -> Image.Image:
    """Return a greyscale copy of the page that looks like it went through a cheap scanner.

    The steps are: shrink the page to scan_dpi, tilt it, blur it, and mix in
    random grain (noise runs from 0 for none to 1 for only grain). Give a
    threshold to turn every pixel pure black or white, like a fax.
    """
    width = round(page.image.width * scan_dpi / page.dpi)
    height = round(page.image.height * scan_dpi / page.dpi)
    scan = page.image.convert("L").resize((width, height), Image.Resampling.BILINEAR)
    scan = scan.rotate(tilt_degrees, resample=Image.Resampling.BICUBIC, fillcolor=255)
    scan = scan.filter(ImageFilter.GaussianBlur(blur_radius))
    grain = Image.frombytes("L", scan.size, rng.randbytes(width * height))
    scan = Image.blend(scan, grain, noise)
    if threshold is not None:
        scan = scan.point(lambda value: 0 if value < threshold else 255)
    return scan


def save_image_pdf(path: Path, title: str, image: Image.Image) -> None:
    """Write a one-page PDF whose only content is the image, stretched to fill the page."""
    pdf = canvas.Canvas(str(path), pagesize=letter, invariant=True)
    pdf.setTitle(title)
    pdf.drawImage(ImageReader(image), 0, 0, width=PAGE_WIDTH_POINTS, height=PAGE_HEIGHT_POINTS)
    pdf.showPage()
    pdf.save()
