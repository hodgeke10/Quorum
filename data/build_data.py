"""Build Quorum's destination, fare and lodging snapshot.

The app never calls a live pricing API — see README for why. Instead it reads
three CSVs with a stable schema. This script regenerates them.

The numbers are a *calibrated synthetic snapshot*: each destination carries a
hand-set base round-trip fare and base nightly rate taken from the typical
published range for that route and city, and the script spreads those across
the year with per-destination seasonal multipliers. They are realistic in
shape and magnitude, not scraped quotes. To use real data instead, replace
fares.csv and lodging.csv with an export in the same columns; nothing else in
the app changes.

Run:  python build_data.py
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent

MONTHS = list(range(1, 13))

# origin airports the app prices from, with a cost-of-origin multiplier that
# reflects how expensive that airport typically is to leave from.
ORIGINS = {
    "BDL": ("Hartford", 1.10),
    "JFK": ("New York", 1.00),
    "EWR": ("Newark", 1.00),
    "LGA": ("New York", 1.02),
    "BOS": ("Boston", 1.03),
    "ORD": ("Chicago", 1.00),
    "ATL": ("Atlanta", 0.97),
    "DFW": ("Dallas", 0.99),
    "DEN": ("Denver", 1.01),
    "LAX": ("Los Angeles", 1.02),
    "SFO": ("San Francisco", 1.05),
    "SEA": ("Seattle", 1.05),
    "MIA": ("Miami", 0.98),
}

# One row per destination. `fare` is a typical round-trip from the US east
# coast and `nightly` a mid-tier room; the script spreads both across the year
# using each destination's own peak and shoulder months. `temps` is
# (summer high, shoulder, winter low) in F, and `south` flips the calendar for
# the southern hemisphere.
def D(code, city, country, region, tags, fare, nightly, peak, shoulder, temps,
      rain, south=False):
    return dict(code=code, city=city, country=country, region=region, tags=tags,
                fare=fare, nightly=nightly, peak=peak, shoulder=shoulder,
                temps=temps, rain=rain, south=south)


DESTS = [
    # ── United States and Canada ──────────────────────────────────────────
    D("DEN", "Denver", "United States", "us-mountain", "outdoors,mountains,nightlife",
      290, 160, [7, 8, 12, 1], [6, 9], (88, 62, 45), "dry"),
    D("SLC", "Salt Lake City", "United States", "us-mountain", "outdoors,mountains,skiing",
      320, 150, [1, 2, 7], [3, 6, 12], (92, 65, 40), "dry"),
    D("JAC", "Jackson Hole", "United States", "us-mountain", "outdoors,mountains,nature,skiing",
      430, 310, [7, 8, 1, 2], [6, 9], (81, 58, 28), "snow-winter"),
    D("BZN", "Bozeman", "United States", "us-mountain", "outdoors,mountains,nature",
      400, 210, [7, 8], [6, 9, 1], (82, 57, 30), "snow-winter"),
    D("MSY", "New Orleans", "United States", "us-south", "food,nightlife,culture,budget",
      260, 170, [2, 3, 4], [10, 11], (91, 78, 62), "wet-summer"),
    D("AUS", "Austin", "United States", "us-south", "food,nightlife,outdoors,budget",
      270, 175, [3, 10, 11], [4, 9], (96, 80, 62), "dry"),
    D("NSH", "Nashville", "United States", "us-south", "music,nightlife,food",
      250, 180, [4, 5, 9, 10], [3, 6], (89, 73, 48), "wet-spring"),
    D("CHS", "Charleston", "United States", "us-south", "food,beach,culture",
      250, 185, [4, 5, 10], [3, 9, 11], (89, 75, 58), "wet-summer"),
    D("SAV", "Savannah", "United States", "us-south", "culture,food,beach,budget",
      260, 165, [3, 4, 10], [5, 11], (91, 76, 60), "wet-summer"),
    D("MIA", "Miami", "United States", "us-south", "beach,nightlife,food,city",
      230, 215, [12, 1, 2, 3], [4, 11], (90, 83, 76), "wet-summer"),
    D("KEY", "Key West", "United States", "us-south", "beach,nightlife,food",
      330, 280, [12, 1, 2, 3], [4, 11], (90, 85, 76), "wet-summer"),
    D("SAN", "San Diego", "United States", "us-west", "beach,food,outdoors",
      340, 215, [6, 7, 8], [5, 9], (78, 72, 66), "dry"),
    D("PDX", "Portland", "United States", "us-west", "food,city,outdoors,nature",
      330, 175, [7, 8], [6, 9], (82, 62, 46), "wet-winter"),
    D("LAS", "Las Vegas", "United States", "us-west", "nightlife,city,food,budget",
      250, 150, [3, 4, 10], [2, 5, 11], (104, 80, 58), "dry"),
    D("PHX", "Phoenix", "United States", "us-west", "outdoors,budget,city",
      260, 165, [1, 2, 3], [11, 12], (106, 85, 67), "dry"),
    D("HNL", "Honolulu", "United States", "us-west", "beach,nature,outdoors",
      660, 265, [6, 7, 12, 1], [5, 9], (88, 84, 80), "wet-winter"),
    D("ANC", "Anchorage", "United States", "us-west", "nature,outdoors,photography",
      540, 190, [6, 7, 8], [5, 9], (66, 48, 22), "mild"),
    D("NYC", "New York", "United States", "us-northeast", "city,food,culture,art,nightlife",
      210, 285, [5, 6, 9, 10, 12], [4, 11], (84, 68, 40), "mild"),
    D("BOS", "Boston", "United States", "us-northeast", "city,culture,food,art",
      215, 250, [6, 9, 10], [5, 7], (82, 64, 36), "mild"),
    D("PHL", "Philadelphia", "United States", "us-northeast", "city,culture,food,budget",
      200, 190, [5, 6, 9, 10], [4, 11], (86, 68, 40), "mild"),
    D("DCA", "Washington", "United States", "us-northeast", "culture,city,art,food",
      205, 220, [4, 5, 9, 10], [6, 11], (88, 70, 42), "mild"),
    D("YUL", "Montreal", "Canada", "us-northeast", "food,culture,city,art",
      300, 185, [6, 7, 8], [5, 9], (79, 60, 25), "snow-winter"),
    D("YQB", "Quebec City", "Canada", "us-northeast", "culture,winter,food,photography",
      340, 190, [7, 8, 2], [6, 9], (76, 56, 20), "snow-winter"),
    D("YYZ", "Toronto", "Canada", "us-northeast", "city,food,culture,art",
      290, 200, [6, 7, 8], [5, 9], (81, 62, 28), "snow-winter"),
    D("YVR", "Vancouver", "Canada", "us-west", "city,nature,outdoors,food",
      390, 215, [7, 8], [6, 9], (74, 60, 42), "wet-winter"),

    # ── Caribbean, Mexico and Central America ─────────────────────────────
    D("CUN", "Cancún", "Mexico", "latam", "beach,nightlife,budget,food",
      420, 165, [1, 2, 3, 12], [4, 11], (88, 84, 80), "wet-summer"),
    D("SJD", "Los Cabos", "Mexico", "latam", "beach,nightlife,outdoors,upscale",
      470, 220, [12, 1, 2, 3], [4, 11], (90, 84, 76), "dry"),
    D("PVR", "Puerto Vallarta", "Mexico", "latam", "beach,food,budget,nightlife",
      430, 150, [12, 1, 2, 3], [4, 11], (90, 85, 78), "wet-summer"),
    D("MEX", "Mexico City", "Mexico", "latam", "city,food,culture,art,budget",
      390, 130, [3, 4, 10, 11], [5, 12], (79, 73, 66), "wet-summer"),
    D("OAX", "Oaxaca", "Mexico", "latam", "food,culture,art,budget",
      460, 110, [10, 11, 12], [3, 4], (85, 79, 70), "wet-summer"),
    D("SJU", "San Juan", "Puerto Rico", "caribbean", "beach,food,culture,budget",
      380, 180, [12, 1, 2, 3], [4, 11], (87, 85, 82), "wet-autumn"),
    D("PUJ", "Punta Cana", "Dominican Republic", "caribbean", "beach,nightlife,upscale",
      450, 230, [12, 1, 2, 3], [4, 11], (89, 86, 81), "wet-autumn"),
    D("MBJ", "Montego Bay", "Jamaica", "caribbean", "beach,music,nightlife,food",
      440, 215, [12, 1, 2, 3], [4, 11], (90, 86, 82), "wet-autumn"),
    D("NAS", "Nassau", "Bahamas", "caribbean", "beach,nightlife,upscale",
      410, 265, [12, 1, 2, 3], [4, 11], (89, 84, 77), "wet-summer"),
    D("AUA", "Aruba", "Aruba", "caribbean", "beach,outdoors,upscale",
      520, 255, [12, 1, 2, 3], [4, 11], (90, 87, 84), "dry"),
    D("SJO", "San José", "Costa Rica", "latam", "nature,outdoors,beach,budget",
      490, 135, [12, 1, 2, 3], [4, 11], (81, 77, 72), "wet-summer"),
    D("PTY", "Panama City", "Panama", "latam", "city,food,beach,budget",
      470, 140, [1, 2, 3], [12, 4], (90, 87, 84), "wet-summer"),
    D("HAV", "Havana", "Cuba", "caribbean", "culture,music,food,photography",
      480, 120, [12, 1, 2, 3], [4, 11], (89, 84, 78), "wet-summer"),

    # ── South America ─────────────────────────────────────────────────────
    D("LIM", "Lima", "Peru", "latam", "food,culture,outdoors,budget",
      690, 120, [6, 7, 8], [5, 9], (80, 72, 64), "dry"),
    D("CUZ", "Cusco", "Peru", "latam", "outdoors,culture,nature,photography",
      760, 130, [6, 7, 8], [5, 9], (68, 65, 60), "wet-summer"),
    D("BOG", "Bogotá", "Colombia", "latam", "city,food,culture,budget",
      560, 115, [12, 1, 7], [6, 8], (68, 66, 63), "wet-spring"),
    D("MDE", "Medellín", "Colombia", "latam", "city,nightlife,food,budget",
      570, 110, [12, 1, 7], [6, 8], (82, 80, 78), "wet-autumn"),
    D("UIO", "Quito", "Ecuador", "latam", "culture,outdoors,nature,budget",
      640, 105, [6, 7, 8, 12], [1, 9], (70, 68, 65), "wet-spring"),
    D("SCL", "Santiago", "Chile", "latam", "city,food,outdoors,mountains",
      820, 150, [12, 1, 2], [11, 3], (86, 68, 48), "dry", True),
    D("EZE", "Buenos Aires", "Argentina", "latam", "city,food,culture,nightlife,art",
      830, 145, [12, 1, 2], [11, 3], (85, 70, 50), "mild", True),
    D("GIG", "Rio de Janeiro", "Brazil", "latam", "beach,nightlife,music,city",
      790, 170, [12, 1, 2], [11, 3], (88, 80, 70), "wet-summer", True),

    # ── Europe ────────────────────────────────────────────────────────────
    D("LIS", "Lisbon", "Portugal", "europe", "city,food,culture,budget,nightlife",
      720, 150, [6, 7, 8], [5, 9, 10], (82, 72, 58), "dry-summer"),
    D("OPO", "Porto", "Portugal", "europe", "food,culture,budget,city",
      730, 130, [6, 7, 8], [5, 9], (79, 68, 54), "wet-winter"),
    D("BCN", "Barcelona", "Spain", "europe", "city,beach,food,nightlife,culture",
      760, 190, [6, 7, 8], [5, 9, 10], (84, 73, 57), "dry-summer"),
    D("MAD", "Madrid", "Spain", "europe", "city,art,food,culture",
      740, 165, [5, 6, 9, 10], [4, 11], (92, 72, 46), "dry-summer"),
    D("PMI", "Palma", "Spain", "europe", "beach,nightlife,outdoors",
      790, 185, [6, 7, 8], [5, 9], (86, 74, 58), "dry-summer"),
    D("IBZ", "Ibiza", "Spain", "europe", "beach,nightlife,music",
      820, 240, [6, 7, 8], [5, 9], (85, 74, 60), "dry-summer"),
    D("MXP", "Milan", "Italy", "europe", "city,food,culture,art",
      780, 185, [6, 7, 9], [4, 5, 10], (84, 70, 45), "mild"),
    D("FCO", "Rome", "Italy", "europe", "culture,food,art,city",
      770, 195, [5, 6, 9, 10], [4, 11], (88, 73, 54), "dry-summer"),
    D("FLR", "Florence", "Italy", "europe", "art,culture,food",
      800, 205, [5, 6, 9, 10], [4, 11], (89, 72, 48), "mild"),
    D("VCE", "Venice", "Italy", "europe", "art,culture,photography,food",
      810, 225, [5, 6, 9, 10], [4, 11], (82, 68, 42), "mild"),
    D("NAP", "Naples", "Italy", "europe", "food,culture,beach,budget",
      790, 150, [6, 7, 9], [5, 10], (87, 73, 54), "dry-summer"),
    D("ATH", "Athens", "Greece", "europe", "beach,culture,food,nightlife",
      810, 175, [6, 7, 8], [5, 9, 10], (92, 76, 57), "dry-summer"),
    D("JTR", "Santorini", "Greece", "europe", "beach,photography,upscale,food",
      890, 290, [6, 7, 8], [5, 9], (84, 74, 58), "dry-summer"),
    D("SPU", "Split", "Croatia", "europe", "beach,outdoors,culture,budget",
      840, 145, [6, 7, 8], [5, 9], (86, 72, 52), "dry-summer"),
    D("DBV", "Dubrovnik", "Croatia", "europe", "beach,culture,photography",
      860, 185, [6, 7, 8], [5, 9], (84, 72, 54), "dry-summer"),
    D("CDG", "Paris", "France", "europe", "city,food,culture,art",
      740, 230, [6, 7, 8], [5, 9, 10], (77, 65, 46), "mild"),
    D("NCE", "Nice", "France", "europe", "beach,food,art,upscale",
      800, 215, [6, 7, 8], [5, 9], (82, 70, 55), "dry-summer"),
    D("AMS", "Amsterdam", "Netherlands", "europe", "city,art,culture,nightlife",
      700, 210, [5, 6, 7, 8], [4, 9], (72, 60, 42), "wet-year-round"),
    D("BER", "Berlin", "Germany", "europe", "city,nightlife,art,culture,budget",
      690, 145, [6, 7, 8], [5, 9], (75, 60, 36), "mild"),
    D("PRG", "Prague", "Czechia", "europe", "culture,city,budget,nightlife",
      710, 125, [5, 6, 9], [4, 7, 10], (76, 60, 34), "mild"),
    D("BUD", "Budapest", "Hungary", "europe", "culture,city,budget,nightlife,food",
      720, 115, [5, 6, 9], [4, 7, 10], (81, 63, 34), "mild"),
    D("KRK", "Kraków", "Poland", "europe", "culture,budget,city,art",
      730, 100, [5, 6, 9], [4, 7], (76, 59, 30), "mild"),
    D("VIE", "Vienna", "Austria", "europe", "culture,art,food,city",
      720, 175, [5, 6, 9], [4, 7, 10], (79, 62, 35), "mild"),
    D("ZRH", "Zurich", "Switzerland", "europe", "mountains,outdoors,upscale,nature",
      760, 265, [6, 7, 8, 12], [5, 9], (76, 60, 34), "mild"),
    D("CPH", "Copenhagen", "Denmark", "europe", "city,food,culture,art",
      710, 230, [6, 7, 8], [5, 9], (71, 57, 34), "wet-year-round"),
    D("ARN", "Stockholm", "Sweden", "europe", "city,culture,nature,art",
      730, 210, [6, 7, 8], [5, 9], (72, 55, 28), "mild"),
    D("OSL", "Oslo", "Norway", "europe", "nature,outdoors,mountains,photography",
      750, 235, [6, 7, 8], [5, 9], (71, 54, 27), "wet-year-round"),
    D("TOS", "Tromsø", "Norway", "europe", "nature,winter,photography,outdoors",
      860, 220, [1, 2, 6, 7], [3, 9], (59, 42, 22), "snow-winter"),
    D("KEF", "Reykjavík", "Iceland", "europe", "outdoors,nature,photography",
      540, 210, [6, 7, 8], [5, 9], (57, 45, 36), "wet-year-round"),
    D("RVN", "Rovaniemi", "Finland", "europe", "outdoors,nature,winter,photography",
      820, 195, [12, 1, 2], [3, 11], (70, 40, 18), "snow-winter"),
    D("DUB", "Dublin", "Ireland", "europe", "nightlife,culture,food,music",
      650, 180, [6, 7, 8], [5, 9], (68, 56, 40), "wet-year-round"),
    D("EDI", "Edinburgh", "Scotland", "europe", "culture,city,nature,photography",
      670, 190, [6, 7, 8], [5, 9], (66, 54, 36), "wet-year-round"),
    D("LHR", "London", "United Kingdom", "europe", "city,culture,art,food,nightlife",
      660, 250, [6, 7, 8, 12], [5, 9], (73, 60, 41), "wet-year-round"),
    D("IST", "Istanbul", "Türkiye", "europe", "culture,food,city,budget",
      790, 135, [5, 6, 9, 10], [4, 11], (84, 70, 46), "wet-winter"),

    # ── Africa and the Middle East ────────────────────────────────────────
    D("RAK", "Marrakech", "Morocco", "africa", "culture,food,budget,photography",
      780, 125, [3, 4, 10, 11], [2, 5], (99, 78, 54), "dry"),
    D("CAI", "Cairo", "Egypt", "africa", "culture,budget,photography",
      860, 120, [10, 11, 3, 4], [2, 12], (95, 80, 58), "dry"),
    D("CPT", "Cape Town", "South Africa", "africa", "beach,outdoors,food,nature",
      980, 160, [12, 1, 2], [11, 3], (79, 70, 55), "wet-winter", True),
    D("NBO", "Nairobi", "Kenya", "africa", "nature,outdoors,photography",
      1050, 150, [7, 8, 1, 2], [6, 9], (78, 74, 68), "wet-spring"),
    D("ZNZ", "Zanzibar", "Tanzania", "africa", "beach,nature,budget",
      1120, 155, [7, 8, 1, 2], [6, 9], (88, 85, 81), "wet-spring"),
    D("DXB", "Dubai", "United Arab Emirates", "middle-east", "city,upscale,beach,nightlife",
      890, 230, [12, 1, 2, 3], [11, 4], (106, 88, 68), "dry"),
    D("TLV", "Tel Aviv", "Israel", "middle-east", "beach,nightlife,food,city",
      880, 215, [4, 5, 9, 10], [3, 11], (88, 76, 58), "wet-winter"),
    D("AMM", "Amman", "Jordan", "middle-east", "culture,outdoors,photography,budget",
      920, 130, [3, 4, 10, 11], [5, 9], (90, 72, 48), "dry"),

    # ── Asia ──────────────────────────────────────────────────────────────
    D("NRT", "Tokyo", "Japan", "asia", "city,food,culture,nightlife",
      980, 175, [3, 4, 10, 11], [5, 9], (86, 70, 48), "wet-summer"),
    D("KIX", "Osaka", "Japan", "asia", "food,city,culture,budget",
      990, 150, [3, 4, 10, 11], [5, 9], (88, 72, 47), "wet-summer"),
    D("CTS", "Sapporo", "Japan", "asia", "winter,skiing,food,nature",
      1030, 160, [1, 2, 7, 8], [6, 9], (78, 58, 24), "snow-winter"),
    D("ICN", "Seoul", "South Korea", "asia", "city,food,nightlife,culture",
      960, 155, [4, 5, 9, 10], [3, 11], (84, 68, 30), "wet-summer"),
    D("TPE", "Taipei", "Taiwan", "asia", "food,city,nature,budget",
      980, 130, [10, 11, 3, 4], [12, 5], (90, 78, 62), "wet-summer"),
    D("HKG", "Hong Kong", "China", "asia", "city,food,nightlife,culture",
      990, 195, [10, 11, 12], [3, 4], (88, 78, 62), "wet-summer"),
    D("BKK", "Bangkok", "Thailand", "asia", "food,city,nightlife,budget,culture",
      1050, 95, [12, 1, 2], [11, 3], (93, 90, 86), "wet-summer"),
    D("HKT", "Phuket", "Thailand", "asia", "beach,nightlife,budget,nature",
      1120, 105, [12, 1, 2, 3], [11, 4], (91, 88, 85), "wet-summer"),
    D("SGN", "Ho Chi Minh City", "Vietnam", "asia", "food,city,budget,culture",
      1080, 85, [12, 1, 2, 3], [11, 4], (92, 89, 85), "wet-summer"),
    D("HAN", "Hanoi", "Vietnam", "asia", "food,culture,budget,city",
      1090, 80, [10, 11, 3, 4], [12, 5], (91, 80, 63), "wet-summer"),
    D("SIN", "Singapore", "Singapore", "asia", "city,food,upscale,nightlife",
      1100, 215, [6, 7, 12], [2, 3], (89, 87, 85), "wet-year-round"),
    D("DPS", "Bali", "Indonesia", "asia", "beach,nature,budget,outdoors",
      1180, 110, [7, 8, 12, 1], [6, 9], (88, 86, 84), "wet-winter"),
    D("KUL", "Kuala Lumpur", "Malaysia", "asia", "city,food,budget,culture",
      1090, 95, [6, 7, 12], [3, 8], (90, 88, 86), "wet-autumn"),
    D("DEL", "Delhi", "India", "asia", "culture,food,budget,photography",
      1000, 90, [10, 11, 2, 3], [12, 4], (104, 82, 56), "wet-summer"),
    D("GOI", "Goa", "India", "asia", "beach,nightlife,budget,food",
      1080, 95, [11, 12, 1, 2], [3, 10], (91, 86, 80), "wet-summer"),
    D("CMB", "Colombo", "Sri Lanka", "asia", "beach,nature,culture,budget",
      1130, 100, [12, 1, 2, 3], [11, 4], (88, 85, 81), "wet-autumn"),
    D("KTM", "Kathmandu", "Nepal", "asia", "mountains,outdoors,culture,nature",
      1150, 85, [10, 11, 3, 4], [9, 5], (84, 72, 46), "wet-summer"),
    D("MLE", "Maldives", "Maldives", "asia", "beach,upscale,nature",
      1280, 390, [12, 1, 2, 3], [11, 4], (88, 86, 84), "wet-summer"),

    # ── Oceania ───────────────────────────────────────────────────────────
    D("SYD", "Sydney", "Australia", "oceania", "beach,city,food,nightlife",
      1320, 210, [12, 1, 2], [11, 3], (81, 71, 60), "wet-autumn", True),
    D("MEL", "Melbourne", "Australia", "oceania", "food,art,city,culture",
      1340, 195, [12, 1, 2], [11, 3], (79, 68, 52), "mild", True),
    D("AKL", "Auckland", "New Zealand", "oceania", "nature,outdoors,food,city",
      1380, 185, [12, 1, 2], [11, 3], (76, 66, 52), "wet-winter", True),
    D("ZQN", "Queenstown", "New Zealand", "oceania", "outdoors,mountains,nature,skiing",
      1450, 215, [12, 1, 2, 7], [11, 3], (72, 58, 38), "mild", True),
    D("NAN", "Fiji", "Fiji", "oceania", "beach,nature,upscale",
      1390, 240, [6, 7, 8], [5, 9], (87, 84, 80), "wet-summer", True),
]

# the six-destination test set: spread across region, climate and price so it
# still exercises every code path
SAMPLE = {"CUN", "LIS", "DEN", "MSY", "KEF", "NRT"}

# How far each region is from the US east coast, as a multiplier on the base
# fare, plus how that changes when leaving from the west coast instead.
REGIONS = {
    "us-northeast": {"distance": 0.70, "west": 1.55},
    "us-south":     {"distance": 0.85, "west": 1.35},
    "us-mountain":  {"distance": 1.00, "west": 0.60},
    "us-west":      {"distance": 1.00, "west": 0.55},
    "caribbean":    {"distance": 1.15, "west": 1.30},
    "latam":        {"distance": 1.25, "west": 1.20},
    "europe":       {"distance": 1.00, "west": 1.22},
    "africa":       {"distance": 1.05, "west": 1.25},
    "middle-east":  {"distance": 1.05, "west": 1.10},
    "asia":         {"distance": 1.00, "west": 0.72},
    "oceania":      {"distance": 1.00, "west": 0.78},
}

WEST_COAST_ORIGINS = {"LAX", "SFO", "SEA", "DEN", "SLC", "PDX"}

# How far a trip is, in the sense that matters to a traveler: hours in the air
# and how many of them you are willing to spend for the nights you get. The
# region is mostly enough, but "latam" spans Cancún and Buenos Aires, so South
# America is called out by country.
SOUTH_AMERICA = {"Peru", "Colombia", "Ecuador", "Chile", "Argentina", "Brazil"}

HAUL_BY_REGION = {
    "us-northeast": "short", "us-south": "short", "us-mountain": "short",
    "us-west": "short", "caribbean": "short", "latam": "medium",
    "europe": "long", "africa": "long", "middle-east": "long",
    "asia": "long", "oceania": "long",
}


def haul_for(region: str, country: str) -> str:
    if country in SOUTH_AMERICA:
        return "long"
    return HAUL_BY_REGION[region]


def season_factor(month: int, peak: list[int], shoulder: list[int]) -> float:
    if month in peak:
        return 1.34
    if month in shoulder:
        return 1.08
    return 0.86


def crowd_index(month: int, peak: list[int], shoulder: list[int]) -> int:
    """1-10, how busy the destination is that month."""
    if month in peak:
        return 9
    if month in shoulder:
        return 6
    return 3


def temp_for(month: int, temps: tuple[int, int, int], southern: bool = False) -> int:
    """Spread a (summer, shoulder, winter) triple across the calendar."""
    hi, mid, lo = temps
    if southern:
        month = (month + 5) % 12 + 1
    # 1.0 at July, 0.0 at January, cosine in between
    warmth = (1 - math.cos((month - 1) / 12 * 2 * math.pi)) / 2
    if warmth >= 0.75:
        base = hi
    elif warmth <= 0.25:
        base = lo
    else:
        base = mid
    # blend so neighbouring months are not flat
    return round(lo + (hi - lo) * warmth * 0.85 + (base - lo) * 0.15)


def rain_days(month: int, profile: str, southern: bool = False) -> int:
    if southern:
        month = (month + 5) % 12 + 1
    summerish = month in (6, 7, 8, 9)
    winterish = month in (11, 12, 1, 2)
    return {
        "wet-summer": 14 if summerish else 7,
        "wet-autumn": 15 if month in (9, 10, 11) else 8,
        "wet-spring": 14 if month in (3, 4, 5) else 8,
        "wet-winter": 15 if winterish else 5,
        "dry-summer": 3 if summerish else 10,
        "wet-year-round": 16 if winterish else 13,
        "snow-winter": 15 if winterish else 9,
        "mild": 11 if winterish else 8,
        "dry": 4 if summerish else 6,
    }[profile]


def main() -> None:
    dest_rows, season_rows, fare_rows, lodging_rows = [], [], [], []

    for d in DESTS:
        code, region, south = d["code"], d["region"], d["south"]
        dest_rows.append({
            "dest_code": code, "city": d["city"], "country": d["country"],
            "region": region, "haul": haul_for(region, d["country"]),
            "tags": d["tags"],
            "in_sample": "yes" if code in SAMPLE else "no",
        })

        for m in MONTHS:
            sf = season_factor(m, d["peak"], d["shoulder"])
            season_rows.append({
                "dest_code": code, "month": m,
                "avg_high_f": temp_for(m, d["temps"], south),
                "rain_days": rain_days(m, d["rain"], south),
                "crowd_index": crowd_index(m, d["peak"], d["shoulder"]),
                "is_peak": "yes" if m in d["peak"] else "no",
            })

            for origin, (_, origin_mult) in ORIGINS.items():
                # Nobody flies to the city they live in; leaving the pair out
                # means the tools can report it as "already there" rather than
                # inventing a fare.
                if origin == code:
                    continue
                dist = REGIONS[region]["distance"]
                if origin in WEST_COAST_ORIGINS:
                    dist *= REGIONS[region]["west"]
                fare = d["fare"] * dist * origin_mult * sf
                fare_rows.append({
                    "origin": origin, "dest_code": code, "month": m,
                    "median_roundtrip_usd": int(round(fare / 5) * 5),
                })

            for tier, mult in (("budget", 0.55), ("mid", 1.0), ("upscale", 1.85)):
                lodging_rows.append({
                    "dest_code": code, "month": m, "tier": tier,
                    "nightly_usd": int(round(d["nightly"] * mult * sf / 5) * 5),
                })

    write(HERE / "destinations.csv", dest_rows)
    write(HERE / "seasonality.csv", season_rows)
    write(HERE / "fares.csv", fare_rows)
    write(HERE / "lodging.csv", lodging_rows)

    print(f"destinations {len(dest_rows)}  seasonality {len(season_rows)}  "
          f"fares {len(fare_rows)}  lodging {len(lodging_rows)}")


def write(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
