# OCR sample images — MetrIQ `/inspection/analyze`

Drop these into the **Inspection** tab (or `curl -F image=@<file> http://127.0.0.1:8000/inspection/analyze`)
to exercise the pipeline: local OCR (`rapidocr-onnxruntime`, PP-OCRv3 weights) →
declaration extraction → product identification → verified Indian Standard candidates.

Nothing here is production data. The `synth_*` labels are generated locally by
`make_synth_labels.py` (in this folder) with **fictional** company / address /
licence / registration details — the products and Indian Standards are real
categories. Regen: `../../backend/.venv/bin/python make_synth_labels.py`.

## Synthetic — known ground truth (use these for pass/fail checks)

| File | What it tests | Expected pipeline outcome |
|---|---|---|
| `synth_clean-declaration.png` | roasted-chana declaration panel, straight & sharp | ~13 OCR regions; 12 declared fields; classified **Roasted Bengal Gram**; standard **MATCHED → IS 18140:2023** |
| `synth_photo-angled.jpg` | same label, ~3.5° rotation + blur + JPEG | same result; PP-OCRv3 tends to drop spaces (`NetQuantity:200g`) — engine, not pipeline |
| `synth_low-light-blurry.jpg` | same label, dark / low-contrast / out of focus | quality flagged **low**; text mostly recovered with character errors; usually still MATCHED |
| `synth_led-lamp.png` | 9 W self-ballasted LED bulb declaration | classified **Self-Ballasted LED Lamp**; standard **MATCHED → IS 16102 (Part 1):2026**. The `BIS CRS Reg. No.` on the label is a registration, not a standard — MetrIQ does not read the IS number off the label. |
| `synth_electric-kettle.png` | 1.5 L / 1500 W electric kettle declaration | classified **Electric Kettle**; standard **MATCHED → IS 367:1993**; compliance STANDARD_ONLY REVIEW (no requirement data) |
| `synth_packaged-water.png` | 1 L packaged drinking water with `IS 14543` printed on its own line | standard **MATCHED → IS 14543:2016**; product confirmed; printed-IS-number check **PASS**; overall REVIEW (2 verified areas not checkable) |
| `synth_noisy-qr-label.png` | poor label: `SCAN QR CODE` as the largest line, `Manufactured by:` followed by `SCANQRCODE` | product name + manufacturer **UNCERTAIN** with no value (evidence kept); no product, no standard, REVIEW |

Ground-truth declaration text — chana labels:

```
ROASTED MASALA CHANA  (Roasted Bengal gram with spices)
Net Quantity: 200 g
M.R.P. Rs. 45.00  (inclusive of all taxes)
Packed by: SUNRISE FOODS PVT LTD
Plot 14, MIDC Industrial Area, Pune 411019, Maharashtra
Mfg Date: 03/2026        Batch No: SR2026-0342
Best Before: 9 months from date of packaging
Consumer Care: care@sunrisefoods.example
Toll Free 1800-000-1234  (Mon-Sat, 9am-6pm)
FSSAI Lic. No. 10012345000123
```

`synth_led-lamp.png` — LED BULB 9W · Net Quantity 1 N · MRP ₹199.00 · Marketed by
LUMENGLOW ELECTRICALS PVT LTD, Gurugram 122051 · Mfg 04/2026 · Batch LG-2604-A ·
BIS CRS Reg. No. R-41000000.

`synth_electric-kettle.png` — ELECTRIC KETTLE 1.5 L · 1500 W · Net Quantity 1 N ·
MRP ₹899.00 · Manufactured by THERMOPOT APPLIANCES PVT LTD, Solan 173205 ·
Mfg 02/2026 · Batch TP-0226-K · ISI Marked CM/L-1234567.

## Real label photos (Wikimedia Commons)

| File | Source | License | Notes |
|---|---|---|---|
| `real_fda-nutrition-facts-2016.png` | Commons: *FDA Nutrition Facts Label 2016* | Public domain (US Gov) | dense small type, ~37 regions, good clean test |
| `real_generic-food-label.png` | Commons: *Food Label* | CC BY-SA 4.0 | tall full label, ~52 regions |
| `real_china-nutrition-facts.png` | Commons: *China nutrition facts label* | CC BY-SA 4.0 | Chinese + Latin — checks the multilingual model |
| `real_confectionery-ingredients-photo.jpg` | Commons: *Ingredients and tartrazine warning on confectionery label* | CC BY-SA 3.0 | real-world **photo** of a curved label, Cyrillic — hard case, English model transliterates poorly (expected) |
| `real_tortilla-chips-ingredients.png` | Commons: *Ingredients label for tortilla chips* | CC BY-SA 4.0 | very low resolution (471×97) — stress case, engine under-detects |

Retrieved 2026-09-08 from `upload.wikimedia.org/wikipedia/commons/…`. Keep this
file with the images if you redistribute them — CC BY-SA requires attribution.

## Quick check-all

```bash
cd samples/ocr-labels
for f in *.png *.jpg; do
  echo "== $f =="
  curl -s -F "image=@$f" http://127.0.0.1:8000/inspection/analyze \
    | python3 -c "import sys,json;d=json.load(sys.stdin);o=d['ocr'];print(o['region_count'],'regions,',round(o['mean_confidence'],2),'conf');print(o['text'][:200])"
done
```
