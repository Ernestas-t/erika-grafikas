import re
from datetime import datetime

import cv2
import numpy as np
import pytesseract
import pytz
from icalendar import Calendar, Event

# --- CONFIG ---
IMAGE_PATH = "grafikas.jpg"
OUTPUT_TXT = "erika_schedule.txt"
DEBUG_GRID = "debug_grid.png"
DEBUG_CELLS = "debug_cells.png"
NUM_DAYS = 31  # number of day‐columns
TARGET_ROW = 3  # 0=header, 1=first staff row, 2=Erika's row

# regex to validate "HH:MM\nHH:MM"
TIME_RGX = re.compile(r"^([01]\d|2[0-3]):[0-5]\d\s*[\r\n]+([01]\d|2[0-3]):[0-5]\d$")

# 1) load & binarize to get just the 1-pixel grid
img = cv2.imread(IMAGE_PATH)
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
_, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

h, w = bw.shape

# 2) extract horizontal & vertical lines
horiz_k = cv2.getStructuringElement(cv2.MORPH_RECT, (w // NUM_DAYS, 1))
vert_k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, h // 10)))
horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, horiz_k)
vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, vert_k)

grid = cv2.bitwise_or(horiz, vert)
cv2.imwrite(DEBUG_GRID, grid)

# 3) find the exact y‐positions of every horizontal grid line
row_sum = grid.sum(axis=1)
# any row whose sum is >50% of max is a grid line
h_thresh = row_sum.max() * 0.5
h_lines = np.where(row_sum > h_thresh)[0]

# cluster them into bands
h_bands = []
current = [h_lines[0]]
for y in h_lines[1:]:
    if y - current[-1] <= 1:
        current.append(y)
    else:
        h_bands.append(int(np.mean(current)))
        current = [y]
h_bands.append(int(np.mean(current)))

# similarly for verticals
col_sum = grid.sum(axis=0)
v_thresh = col_sum.max() * 0.5
v_lines = np.where(col_sum > v_thresh)[0]

v_bands = []
current = [v_lines[0]]
for x in v_lines[1:]:
    if x - current[-1] <= 1:
        current.append(x)
    else:
        v_bands.append(int(np.mean(current)))
        current = [x]
v_bands.append(int(np.mean(current)))

# 3.5) Extract month from header
header_bottom = h_bands[0] - 2
header_crop = gray[0:header_bottom, :]
month_txt = pytesseract.image_to_string(header_crop, config="--psm 7").splitlines()
# pick the first non-empty line and clean artifacts
month = next((ln.strip() for ln in month_txt if ln.strip()), "Unknown")
month = re.sub(r"[^\w\s]", "", month).strip()  # remove punctuation/artifacts

# now h_bands are Y coords of each grid‐line, v_bands are X coords
# 4) build every cell rect = between successive lines
cells = []
for r in range(len(h_bands) - 1):
    y1 = h_bands[r] + 1
    y2 = h_bands[r + 1] - 1
    for c in range(len(v_bands) - 1):
        x1 = v_bands[c] + 1
        x2 = v_bands[c + 1] - 1
        cells.append((r, c, x1, y1, x2 - x1, y2 - y1))

# 5) debug‐dump a few boxes (just outline the entire grid)
overlay = img.copy()
for _, _, x, y, ww, hh in cells:
    cv2.rectangle(overlay, (x, y), (x + ww, y + hh), (0, 255, 0), 1)
cv2.imwrite(DEBUG_CELLS, overlay)

# 6) pick out Erika's row
# rows are 0.., header is row 0, Sigita row 1, Erika row 2 == TARGET_ROW
erika_cells = [rect for rect in cells if rect[0] == TARGET_ROW]
# within that, skip the first column (name) if necessary
if len(erika_cells) > NUM_DAYS:
    erika_cells = [r for r in erika_cells if r[1] > 0][:NUM_DAYS]
elif len(erika_cells) < NUM_DAYS:
    raise RuntimeError(f"Found only {len(erika_cells)} columns for Erika's row")

# sort by column index
erika_cells.sort(key=lambda r: r[1])

# 7) OCR each day
schedules = []
for _, _, x, y, ww, hh in erika_cells:
    cell = gray[y : y + hh, x : x + ww]
    # small border crop
    if hh > 20 and ww > 20:
        cell = cell[3 : hh - 3, 3 : ww - 3]

    # adaptive threshold, fallback to Otsu
    try:
        thr = cv2.adaptiveThreshold(
            cell,
            255,
            cv2.ADAPTIVE_THRESH_MEAN_C,
            cv2.THRESH_BINARY_INV,
            blockSize=15,
            C=8,
        )
    except cv2.error:
        _, thr = cv2.threshold(cell, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # deskew via min‐area rect
    coords = np.column_stack(np.where(thr > 0))
    if coords.size > 0:
        rect = cv2.minAreaRect(coords)
        angle = rect[-1]
        if angle < -45:
            angle += 90
        M = cv2.getRotationMatrix2D((ww // 2, hh // 2), angle, 1.0)
        thr = cv2.warpAffine(thr, M, (ww, hh), flags=cv2.INTER_CUBIC)

    txt = pytesseract.image_to_string(
        thr, config="--psm 6 -c tessedit_char_whitelist=0123456789:\n"
    ).strip()

    # --- NEW: skip pure‐letter cells (day‐offs) ---
    # if there's no digit in the OCR result, treat as blank
    if not any(ch.isdigit() for ch in txt):
        schedules.append("")
        continue
    # ----------------------------------------------

    # retry at 150%+Otsu if needed
    if not TIME_RGX.match(txt):
        up = cv2.resize(cell, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
        _, up_thr = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        txt2 = pytesseract.image_to_string(
            up_thr, config="--psm 6 -c tessedit_char_whitelist=0123456789:\n"
        ).strip()
        if TIME_RGX.match(txt2):
            txt = txt2

    lines = [ln for ln in txt.splitlines() if ln.strip()]
    schedules.append("\n".join(lines))

# 8) dump to text
filtered_schedules = []
for i, block in enumerate(schedules, 1):
    # Only keep days that match the HH:MM\nHH:MM format
    if TIME_RGX.match(block):
        filtered_schedules.append((i, block))

with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
    f.write(f"Schedule for: {month}\n\n")
    for day_num, block in filtered_schedules:
        f.write(f"Day {day_num:2d}:\n{block}\n\n")

print(f"✓ Extracted {len(filtered_schedules)} valid days for {month} → {OUTPUT_TXT}")


# 9) Generate .ics calendar file
def create_ics_calendar(month_name, filtered_schedules):
    """Create an .ics calendar file from the filtered schedules."""
    # Lithuanian month names to numbers
    months = {
        "sausis": 1,
        "vasaris": 2,
        "kovas": 3,
        "balandis": 4,
        "gegužė": 5,
        "birželis": 6,
        "liepa": 7,
        "rugpjūtis": 8,
        "rugsėjis": 9,
        "spalis": 10,
        "lapkritis": 11,
        "gruodis": 12,
    }

    month_num = months.get(month_name.lower(), 7)  # default to July
    year = datetime.now().year

    # Create calendar
    cal = Calendar()
    cal.add("prodid", "-//Work Schedule Generator//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", f"Work Schedule - {month_name} {year}")
    cal.add("x-wr-caldesc", f"Work shifts for {month_name} {year}")

    timezone = pytz.timezone("Europe/Vilnius")  # Lithuania timezone

    created_events = 0
    for day_num, schedule_block in filtered_schedules:
        try:
            # Parse start and end times from the schedule block
            lines = schedule_block.strip().split("\n")
            if len(lines) >= 2:
                start_time = lines[0].strip()
                end_time = lines[1].strip()

                # Create datetime objects
                start_dt = datetime(
                    year, month_num, day_num, int(start_time[:2]), int(start_time[3:])
                )
                end_dt = datetime(
                    year, month_num, day_num, int(end_time[:2]), int(end_time[3:])
                )

                # Localize to timezone
                start_dt = timezone.localize(start_dt)
                end_dt = timezone.localize(end_dt)

                # Create event
                event = Event()
                event.add("summary", "Darbas")
                event.add("dtstart", start_dt)
                event.add("dtend", end_dt)
                event.add("description", f"Work shift: {start_time} - {end_time}")
                event.add(
                    "location", "Mindaugo g. 25, Vilnius, Lithuania"
                )  # Replace with actual address
                event.add("status", "CONFIRMED")

                # Add unique ID
                event.add(
                    "uid",
                    f"work-shift-{year}-{month_num:02d}-{day_num:02d}@workschedule.local",
                )

                cal.add_component(event)
                created_events += 1

        except (ValueError, IndexError) as e:
            print(f"⚠️  Skipping day {day_num}: {e}")

    # Write to file
    ics_filename = f"work_schedule_{month_name.lower()}_{year}.ics"
    with open(ics_filename, "wb") as f:
        f.write(cal.to_ical())

    print(f"📅 Created calendar file: {ics_filename}")
    print(f"✅ {created_events} work shifts added to calendar")
    print(f"📱 Import this file into any calendar app:")
    print(f"   • Google Calendar: Settings → Import & Export → Import")
    print(f"   • Outlook: File → Open & Export → Import/Export")
    print(f"   • Apple Calendar: File → Import")
    print(f"   • Mobile: Open file, choose calendar app")

    return ics_filename


# Generate the calendar file
ics_file = create_ics_calendar(month, filtered_schedules)
print(f"🎉 Calendar generation complete!")
