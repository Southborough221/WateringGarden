#!/usr/bin/env python3
"""
Vegetable watering advisor.
Fetches live weather (Open-Meteo, no API key), decides water / skip,
and emails you the verdict. Designed to run daily via GitHub Actions.
"""
import os
import smtplib
import ssl
from email.message import EmailMessage

import requests

# ─────────────────────────────────────────────────────────────
#  YOUR GARDEN — set these once
# ─────────────────────────────────────────────────────────────
LAT, LON   = 51.0362, 0.5119    # garden, East Heath Barn, TN18 4RD
PLOT_M2    = 4.0                # bed size in square metres
NEED_MM_WK = 25.0               # weekly water need in mm (see notes below)
#  Crop guide for NEED_MM_WK:
#    Thirsty (tomatoes, courgettes, beans, cucumber) ~30
#    Average mixed veg bed                           ~25
#    Roots/alliums (carrots, onions, beetroot)       ~20
#    Herbs / Mediterranean (rosemary, thyme)         ~12

SOIL = "clay"  # "clay", "loam", or "sand" — your bed's soil
#  Local note (TN18 4RD): Stream Lane soil is Wealden clay + Tunbridge Wells
#  sand. Clay holds water longer, so it waters less often; sand dries fast.
#  Clay is set as default; switch to "sand" for free-draining patches.

# Decision thresholds (mm) — base values, adjusted by SOIL below
RAIN_AHEAD_MM = 5.0    # skip if >= this much rain expected next 48h
RAIN_PAST_MM  = 8.0    # skip if >= this much fell in past 48h
HOT_TEMP_C    = 28.0   # hot days = water now, not just today
HUMID_PCT     = 80.0   # very humid air slows soil drying

# Soil adjusts how long water lingers. Clay holds it (skip more readily);
# sand drains (water more readily). Loam is the neutral middle.
SOIL_FACTORS = {
    "clay": {"past_mult": 1.4, "need_mult": 0.85},   # rain counts longer, needs less
    "loam": {"past_mult": 1.0, "need_mult": 1.0},
    "sand": {"past_mult": 0.7, "need_mult": 1.2},    # rain drains away, needs more
}
_sf = SOIL_FACTORS.get(SOIL, SOIL_FACTORS["loam"])
RAIN_PAST_MM = RAIN_PAST_MM * _sf["past_mult"]
NEED_MM_WK   = NEED_MM_WK * _sf["need_mult"]


def get_weather():
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": LAT, "longitude": LON,
        "hourly": "precipitation,relative_humidity_2m,temperature_2m",
        "past_days": 2, "forecast_days": 3, "timezone": "auto",
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()["hourly"]


def advise(h):
    times  = h["time"]
    now    = len(times) - 72          # index for ~now (2 past days loaded)
    precip = h["precipitation"]
    hum    = h["relative_humidity_2m"]
    temp   = h["temperature_2m"]

    rain_past  = sum(p for p in precip[max(0, now - 48):now] if p)
    rain_ahead = sum(p for p in precip[now:now + 48] if p)
    avg_hum    = sum(hum[now:now + 48]) / 48
    max_temp   = max(temp[now:now + 48])

    reasons = []
    water = True

    if rain_ahead >= RAIN_AHEAD_MM:
        water = False
        reasons.append(f"{rain_ahead:.1f}mm rain due next 48h "
                       f"(~{rain_ahead * PLOT_M2:.0f} L free on your bed)")
    if rain_past >= RAIN_PAST_MM:
        water = False
        reasons.append(f"{rain_past:.1f}mm already fell past 48h "
                       f"(~{rain_past * PLOT_M2:.0f} L)")
    if avg_hum >= HUMID_PCT and rain_ahead > 1:
        water = False
        reasons.append(f"humid air ({avg_hum:.0f}%) slows drying")

    if water:
        urgency = "NOW (hot)" if max_temp >= HOT_TEMP_C else "today"
        reasons.append(f"dry ahead ({rain_ahead:.1f}mm), high {max_temp:.0f}°C")
        verdict = f"WATER {urgency}"
        emoji = "WATER"
    else:
        verdict = "SKIP watering"
        emoji = "SKIP"

    body = (
        f"{emoji}: {verdict}\n\n"
        + "\n".join(f"- {r}" for r in reasons)
        + f"\n\nPlot: {PLOT_M2:.0f} m2 | {SOIL} soil | weekly need ~{NEED_MM_WK:.0f}mm"
    )
    return verdict, body


def send_email(subject, body):
    user = os.environ["GMAIL_USER"]
    pw   = os.environ["GMAIL_APP_PW"]
    to   = os.environ.get("MAIL_TO", user)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    msg.set_content(body)

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as s:
        s.login(user, pw)
        s.send_message(msg)


if __name__ == "__main__":
    verdict, body = advise(get_weather())
    print(body)
    if os.environ.get("GMAIL_USER"):
        send_email(f"Veg garden: {verdict}", body)
        print("\n[email sent]")
    else:
        print("\n[no GMAIL_USER set — printed only]")
