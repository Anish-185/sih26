"""Generate synthetic Indian legal-metrology declaration labels for OCR / pipeline
checks.

All company / address / licence / registration details are fictional. The
products and Indian Standards are real categories. Output -> this folder.
"""
from __future__ import annotations

import os
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

OUT = os.path.dirname(os.path.abspath(__file__))
SANS = "/usr/share/fonts/liberation/LiberationSans-Regular.ttf"
SANS_B = "/usr/share/fonts/liberation/LiberationSans-Bold.ttf"

# (text, font size, bold). "" is a vertical gap.
Line = tuple[str, int, bool]

CHANA: list[Line] = [
    ("ROASTED MASALA CHANA", 54, True),
    ("(Roasted Bengal gram with spices)", 30, False),
    ("", 18, False),
    ("Net Quantity: 200 g", 40, True),
    ("M.R.P. Rs. 45.00  (inclusive of all taxes)", 34, True),
    ("", 12, False),
    ("Packed by: SUNRISE FOODS PVT LTD", 30, False),
    ("Plot 14, MIDC Industrial Area, Pune 411019, Maharashtra", 26, False),
    ("Mfg Date: 03/2026        Batch No: SR2026-0342", 28, False),
    ("Best Before: 9 months from date of packaging", 28, False),
    ("", 12, False),
    ("Consumer Care: care@sunrisefoods.example", 26, False),
    ("Toll Free 1800-000-1234  (Mon-Sat, 9am-6pm)", 26, False),
    ("FSSAI Lic. No. 10012345000123", 26, False),
]

LED_LAMP: list[Line] = [
    ("LED BULB 9W", 54, True),
    ("Self-ballasted LED lamp, Cool Daylight 6500K", 28, False),
    ("Input: 220-240V ~ 50Hz   Base: B22", 26, False),
    ("", 14, False),
    ("Net Quantity: 1 N", 40, True),
    ("M.R.P. Rs. 199.00  (inclusive of all taxes)", 34, True),
    ("", 12, False),
    ("Marketed by: LUMENGLOW ELECTRICALS PVT LTD", 28, False),
    ("Plot 27, Sector 8, IMT Manesar, Gurugram 122051, Haryana", 24, False),
    ("Mfg Date: 04/2026        Batch No: LG-2604-A", 26, False),
    ("Warranty: 24 months from date of purchase", 26, False),
    ("", 12, False),
    ("BIS CRS Reg. No. R-41000000", 24, False),
    ("Consumer Care: support@lumenglow.example", 24, False),
    ("Toll Free 1800-200-4545", 24, False),
]

ELECTRIC_KETTLE: list[Line] = [
    ("ELECTRIC KETTLE 1.5 L", 52, True),
    ("Model EK-15S  |  Stainless steel body", 28, False),
    ("Rated: 220-240V ~ 50Hz   1500 W", 26, False),
    ("", 14, False),
    ("Net Quantity: 1 N", 40, True),
    ("M.R.P. Rs. 899.00  (inclusive of all taxes)", 34, True),
    ("", 12, False),
    ("Manufactured by: THERMOPOT APPLIANCES PVT LTD", 26, False),
    ("Survey 112, Baddi Industrial Area, Solan 173205, Himachal Pradesh", 22, False),
    ("Mfg Date: 02/2026        Batch No: TP-0226-K", 26, False),
    ("Warranty: 1 year on product, 2 years on element", 24, False),
    ("", 12, False),
    ("ISI Marked   CM/L-1234567", 24, False),
    ("Consumer Care: care@thermopot.example", 24, False),
    ("Toll Free 1800-300-7788", 24, False),
]

PACKAGED_WATER: list[Line] = [
    ("AQUA SPRING", 54, True),
    ("PACKAGED DRINKING WATER", 40, True),
    ("", 14, False),
    ("Net Quantity: 1 L", 40, True),
    ("M.R.P. Rs. 20.00  (inclusive of all taxes)", 34, True),
    ("", 12, False),
    ("Packed by: CLEARFLOW BEVERAGES PVT LTD", 28, False),
    ("Plot 9, GIDC Industrial Estate, Vapi 396195, Gujarat", 24, False),
    ("Pkd Date: 05/2026        Batch No: CF-0526-B", 26, False),
    ("Best Before: 6 months from packaging", 26, False),
    ("", 12, False),
    ("ISI Mark", 24, False),
    ("IS 14543", 34, True),
    ("CM/L-7654321", 24, False),
    ("FSSAI Lic. No. 10099999000456", 24, False),
    ("Consumer Care: care@clearflow.example", 24, False),
]

# Poor OCR / packaging noise: the 'Manufactured by' value is a QR prompt, and the
# largest line on the panel is the QR prompt, not the product name.
NOISY_LABEL: list[Line] = [
    ("SCAN QR CODE", 60, True),
    ("Net Quantity: 500 g", 34, True),
    ("M.R.P. Rs. 60.00", 30, True),
    ("Manufactured by:", 26, False),
    ("SCANQRCODE", 26, False),
    ("www.example-foods.example", 22, False),
]

PRODUCTS: dict[str, list[Line]] = {
    "chana": CHANA,
    "led-lamp": LED_LAMP,
    "electric-kettle": ELECTRIC_KETTLE,
}


def render_base(lines: list[Line], height: int = 1150) -> Image.Image:
    W, H = 1000, height
    img = Image.new("RGB", (W, H), "#ece8dc")
    d = ImageDraw.Draw(img)
    d.rectangle([24, 24, W - 24, H - 24], outline="#1a1a1a", width=4)
    d.text((60, 44), "PRINCIPAL DISPLAY PANEL", font=ImageFont.truetype(SANS_B, 24),
           fill="#1a1a1a")
    y = 110
    for text, size, bold in lines:
        if not text:
            y += size
            continue
        font = ImageFont.truetype(SANS_B if bold else SANS, size)
        d.text((60, y), text, font=font, fill="#111111")
        y += size + 16
    return img


def save(img: Image.Image, name: str, **kw) -> None:
    path = os.path.join(OUT, name)
    img.save(path, **kw)
    print(f"  wrote {name}  {img.size[0]}x{img.size[1]}  {os.path.getsize(path)//1024} KB")


def main() -> None:
    os.makedirs(OUT, exist_ok=True)

    # The chana label doubles as the clean / angled / low-light OCR test set.
    chana = render_base(CHANA)
    save(chana, "synth_clean-declaration.png", format="PNG")

    photo = chana.rotate(-3.5, expand=True, fillcolor="#e9e7de", resample=Image.BICUBIC)
    photo = photo.filter(ImageFilter.GaussianBlur(1.1))
    photo = ImageEnhance.Contrast(photo).enhance(0.92)
    photo = ImageEnhance.Color(photo).enhance(1.15)
    save(photo, "synth_photo-angled.jpg", format="JPEG", quality=72)

    dim = ImageEnhance.Brightness(chana).enhance(0.45)
    dim = ImageEnhance.Contrast(dim).enhance(0.70)
    dim = dim.filter(ImageFilter.GaussianBlur(2.4))
    dim = dim.rotate(1.5, expand=True, fillcolor="#20201c", resample=Image.BICUBIC)
    save(dim, "synth_low-light-blurry.jpg", format="JPEG", quality=55)

    # One clean declaration panel per additional product.
    save(render_base(LED_LAMP), "synth_led-lamp.png", format="PNG")
    save(render_base(ELECTRIC_KETTLE), "synth_electric-kettle.png", format="PNG")
    save(render_base(PACKAGED_WATER), "synth_packaged-water.png", format="PNG")
    save(render_base(NOISY_LABEL, height=620), "synth_noisy-qr-label.png", format="PNG")


if __name__ == "__main__":
    main()
