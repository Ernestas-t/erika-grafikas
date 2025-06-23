import base64
import json
import os
import re
import tempfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler

import cv2
import numpy as np
import pytesseract
import pytz
from icalendar import Calendar, Event


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            # Set CORS headers
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Type", "application/json")
            self.end_headers()

            # Read the request body
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)

            # Parse JSON data
            data = json.loads(post_data.decode("utf-8"))
            image_data = base64.b64decode(data["image"])

            # Create temporary file
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_file:
                temp_file.write(image_data)
                image_path = temp_file.name

            try:
                # Process the image
                ics_content = process_schedule_image(image_path)

                response = {
                    "success": True,
                    "ics_content": ics_content,
                    "filename": f'darbo_grafikas_{datetime.now().strftime("%Y_%m")}.ics',
                }
                self.wfile.write(json.dumps(response).encode())

            finally:
                # Clean up temp file
                if os.path.exists(image_path):
                    os.unlink(image_path)

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()

            response = {"success": False, "error": str(e)}
            self.wfile.write(json.dumps(response).encode())

    def do_OPTIONS(self):
        # Handle CORS preflight
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def process_schedule_image(image_path):
    """Process the schedule image and return ICS content"""

    # Your existing main.py logic, adapted:
    NUM_DAYS = 31
    TARGET_ROW = 3

    # regex to validate "HH:MM\nHH:MM"
    TIME_RGX = re.compile(r"^([01]\d|2[0-3]):[0-5]\d\s*[\r\n]+([01]\d|2[0-3]):[0-5]\d$")

    # Load & process image
    img = cv2.imread(image_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    h, w = bw.shape

    # Extract horizontal & vertical lines
    horiz_k = cv2.getStructuringElement(cv2.MORPH_RECT, (w // NUM_DAYS, 1))
    vert_k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, h // 10)))
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, horiz_k)
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, vert_k)

    grid = cv2.bitwise_or(horiz, vert)

    # Find grid lines
    row_sum = grid.sum(axis=1)
    h_thresh = row_sum.max() * 0.5
    h_lines = np.where(row_sum > h_thresh)[0]

    # Cluster horizontal lines
    h_bands = []
    current = [h_lines[0]]
    for y in h_lines[1:]:
        if y - current[-1] <= 1:
            current.append(y)
        else:
            h_bands.append(int(np.mean(current)))
            current = [y]
    h_bands.append(int(np.mean(current)))

    # Same for vertical lines
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

    # Extract month from header
    header_bottom = h_bands[0] - 2
    header_crop = gray[0:header_bottom, :]
    month_txt = pytesseract.image_to_string(header_crop, config="--psm 7").splitlines()
    month = next((ln.strip() for ln in month_txt if ln.strip()), "Unknown")
    month = re.sub(r"[^\w\s]", "", month).strip()

    # Build cells
    cells = []
    for r in range(len(h_bands) - 1):
        y1 = h_bands[r] + 1
        y2 = h_bands[r + 1] - 1
        for c in range(len(v_bands) - 1):
            x1 = v_bands[c] + 1
            x2 = v_bands[c + 1] - 1
            cells.append((r, c, x1, y1, x2 - x1, y2 - y1))

    # Get Erika's row cells
    erika_cells = [rect for rect in cells if rect[0] == TARGET_ROW]
    if len(erika_cells) > NUM_DAYS:
        erika_cells = [r for r in erika_cells if r[1] > 0][:NUM_DAYS]

    erika_cells.sort(key=lambda r: r[1])

    # OCR each day
    schedules = []
    for _, _, x, y, ww, hh in erika_cells:
        cell = gray[y : y + hh, x : x + ww]

        if hh > 20 and ww > 20:
            cell = cell[3 : hh - 3, 3 : ww - 3]

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
            _, thr = cv2.threshold(
                cell, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
            )

        # Deskew
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

        # Skip non-digit cells
        if not any(ch.isdigit() for ch in txt):
            schedules.append("")
            continue

        # Retry if needed
        if not TIME_RGX.match(txt):
            up = cv2.resize(cell, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
            _, up_thr = cv2.threshold(
                up, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
            )
            txt2 = pytesseract.image_to_string(
                up_thr, config="--psm 6 -c tessedit_char_whitelist=0123456789:\n"
            ).strip()
            if TIME_RGX.match(txt2):
                txt = txt2

        lines = [ln for ln in txt.splitlines() if ln.strip()]
        schedules.append("\n".join(lines))

    # Filter valid schedules
    filtered_schedules = []
    for i, block in enumerate(schedules, 1):
        if TIME_RGX.match(block):
            filtered_schedules.append((i, block))

    # Generate ICS
    return create_ics_calendar(month, filtered_schedules)


def create_ics_calendar(month_name, filtered_schedules):
    """Create ICS calendar content"""
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

    month_num = months.get(month_name.lower(), datetime.now().month)
    year = datetime.now().year

    cal = Calendar()
    cal.add("prodid", "-//Work Schedule Generator//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", f"Darbo Grafikas - {month_name} {year}")

    timezone = pytz.timezone("Europe/Vilnius")

    for day_num, schedule_block in filtered_schedules:
        try:
            lines = schedule_block.strip().split("\n")
            if len(lines) >= 2:
                start_time = lines[0].strip()
                end_time = lines[1].strip()

                start_dt = datetime(
                    year, month_num, day_num, int(start_time[:2]), int(start_time[3:])
                )
                end_dt = datetime(
                    year, month_num, day_num, int(end_time[:2]), int(end_time[3:])
                )

                start_dt = timezone.localize(start_dt)
                end_dt = timezone.localize(end_dt)

                event = Event()
                event.add("summary", "Darbas")
                event.add("dtstart", start_dt)
                event.add("dtend", end_dt)
                event.add("description", f"Darbo pamaina: {start_time} - {end_time}")
                event.add("location", "Darbovietė")
                event.add("status", "CONFIRMED")
                event.add(
                    "uid",
                    f"work-shift-{year}-{month_num:02d}-{day_num:02d}@workschedule.local",
                )

                cal.add_component(event)

        except (ValueError, IndexError):
            continue

    return cal.to_ical().decode("utf-8")
