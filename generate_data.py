#!/usr/bin/env python3
"""
Generate synthetic data for the car rental database.

Usage:
    pip install faker
    python generate_data.py                      # builds instance/car_rental.sqlite3 from sql/schema.sql
    python generate_data.py --db test.sqlite3 --seed 7

The database is rebuilt from schema.sql on every run, and the random seed is fixed,
so every team member (and the grader) gets exactly the same data.

How the data is kept realistic:
  * Each vehicle gets its own timeline of rentals and maintenance jobs, generated
    back to back, so a car is never double-booked or rented while in the shop.
  * Rental status follows from the dates relative to a fixed "today" (NOW):
    future -> reserved/cancelled, ongoing or overdue -> active, past -> completed.
  * Payments only exist for active (deposit) and completed rentals, and add up to
    (days rented x agreed daily rate).
  * Odometer readings grow with every completed rental.
"""

import argparse
import math
import os
import random
import sqlite3
from datetime import datetime, timedelta

from faker import Faker

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NOW = datetime(2026, 11, 21, 12, 0, 0)          # fixed "today" -> reproducible statuses
HISTORY_START = datetime(2025, 6, 1, 9, 0, 0)    # first day of business data
BOOKING_HORIZON = NOW + timedelta(days=30)       # future reservations up to 30 days out
FMT = "%Y-%m-%d %H:%M:%S"

NUM_CUSTOMERS = 120
NUM_VEHICLES = 30

# (category_name, standard_daily_rate_cents)
CATEGORIES = [
    ("Economy", 3900),
    ("Compact", 4500),
    ("Midsize", 5500),
    ("SUV", 7500),
    ("Luxury", 12900),
]

MODELS = {
    "Economy": [("Nissan", "Versa"), ("Mitsubishi", "Mirage"), ("Kia", "Rio")],
    "Compact": [("Toyota", "Corolla"), ("Honda", "Civic"), ("Hyundai", "Elantra")],
    "Midsize": [("Toyota", "Camry"), ("Honda", "Accord"), ("Nissan", "Altima")],
    "SUV":     [("Toyota", "RAV4"), ("Ford", "Explorer"), ("Chevrolet", "Tahoe")],
    "Luxury":  [("BMW", "5 Series"), ("Mercedes-Benz", "E-Class"), ("Lexus", "ES")],
}

# service_type -> (min_cost_cents, max_cost_cents, min_hours, max_hours)
SERVICES = {
    "Oil change":          (4000, 9000, 1, 3),
    "Tire rotation":       (2500, 6000, 1, 2),
    "Brake service":       (15000, 40000, 4, 30),
    "State inspection":    (2000, 5000, 1, 4),
    "Battery replacement": (12000, 25000, 1, 3),
    "Detailing":           (8000, 15000, 3, 8),
    "Collision repair":    (60000, 250000, 48, 240),
}

PAYMENT_METHODS = ["card", "card", "card", "card", "transfer", "cash"]
VIN_CHARS = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"   # real VINs never use I, O, Q


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def ts(dt):
    """Format a datetime for storage (ISO text sorts and compares correctly in SQLite)."""
    return dt.strftime(FMT) if dt else None


def business_hour(dt):
    """Snap a datetime to a random opening-hours time (08:00-18:00) on the same day."""
    return dt.replace(hour=random.randint(8, 17), minute=random.choice([0, 15, 30, 45]), second=0)


def make_vin(used):
    while True:
        vin = "".join(random.choices(VIN_CHARS, k=17))
        if vin not in used:
            used.add(vin)
            return vin


def make_plate(used):
    while True:
        plate = "".join(random.choices("ABCDEFGHJKLMNPRSTUVWXYZ", k=3)) + " " + \
                "".join(random.choices("0123456789", k=3))
        if plate not in used:
            used.add(plate)
            return plate


def days_charged(start, end):
    """Rentals are billed per started 24-hour period, minimum one day."""
    return max(1, math.ceil((end - start).total_seconds() / 86400))


# ---------------------------------------------------------------------------
# Per-vehicle timeline: rentals and maintenance never overlap
# ---------------------------------------------------------------------------
def build_timeline(standard_rate):
    """Return (rentals, maintenance_jobs, km_driven) for one vehicle."""
    rentals, jobs, km_driven = [], [], 0
    t = business_hour(HISTORY_START + timedelta(days=random.randint(0, 45)))

    while True:
        # idle time on the lot before the next event
        t = business_hour(t + timedelta(days=random.randint(2, 35)))
        if t >= BOOKING_HORIZON:
            break

        # --- maintenance job (only in the past) -----------------------------
        # a car whose last event ends just before "today" may be in the shop right now
        in_shop_now = NOW - timedelta(days=7) < t < NOW and random.random() < 0.5
        if in_shop_now or (t < NOW and random.random() < 0.20):
            service = random.choice(list(SERVICES))
            lo_cost, hi_cost, lo_h, hi_h = SERVICES[service]
            done = t + timedelta(hours=random.randint(lo_h, hi_h))
            if in_shop_now or done > NOW:
                # still in the shop today: open job, no further bookings for this car
                jobs.append(dict(service_type=service, started_at=t, completed_at=None,
                                 cost_cents=random.randint(lo_cost, hi_cost) // 100 * 100))
                break
            jobs.append(dict(service_type=service, started_at=t, completed_at=done,
                             cost_cents=random.randint(lo_cost, hi_cost) // 100 * 100))
            t = done
            continue

        # --- rental ---------------------------------------------------------
        length = random.choices(range(1, 15), weights=[8, 10, 12, 10, 8, 6, 9, 4, 3, 3, 2, 2, 1, 3])[0]
        pickup = t
        due = pickup + timedelta(days=length)
        # most customers pay the standard rate; some get a promo or a peak surcharge
        rate = int(standard_rate * random.choice([1.0, 1.0, 1.0, 1.0, 0.9, 0.85, 1.15]) // 100 * 100)

        rental = dict(pickup_at=pickup, due_at=due, returned_at=None,
                      agreed_daily_rate_cents=rate, status=None)

        if pickup > NOW:                                   # booked for the future
            rental["status"] = "cancelled" if random.random() < 0.12 else "reserved"
            next_free = pickup if rental["status"] == "cancelled" else due
        elif random.random() < 0.05:                       # past booking, never picked up
            rental["status"] = "cancelled"
            next_free = pickup
        else:                                              # picked up
            if NOW - timedelta(days=4) < due < NOW and random.random() < 0.5:
                returned = NOW + timedelta(days=1)         # due recently, still not back: overdue
            elif random.random() < 0.10:                   # late return: 1-3 days over
                returned = business_hour(due + timedelta(days=random.randint(1, 3)))
            else:                                          # on time or a day early
                returned = business_hour(due - timedelta(days=random.choice([0, 0, 0, 1])))
            if returned <= pickup:
                returned = pickup + timedelta(hours=random.randint(3, 8))

            if returned > NOW:                             # still out (possibly overdue)
                rental["status"] = "active"
                next_free = max(due, NOW) + timedelta(days=1)
            else:
                rental["status"] = "completed"
                rental["returned_at"] = returned
                km_driven += days_charged(pickup, returned) * random.randint(40, 260)
                next_free = returned

        rentals.append(rental)
        t = next_free

    return rentals, jobs, km_driven


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Build and populate the car rental database.")
    # Same location the Flask app uses (app.py): $DATABASE_PATH, else instance/car_rental.sqlite3
    default_db = os.environ.get("DATABASE_PATH", os.path.join(here, "instance", "car_rental.sqlite3"))
    ap.add_argument("--db", default=default_db, help="output database file")
    ap.add_argument("--schema", default=os.path.join(here, "sql", "schema.sql"), help="schema file to load")
    ap.add_argument("--seed", type=int, default=42, help="random seed (same seed = same data)")
    args = ap.parse_args()

    random.seed(args.seed)
    Faker.seed(args.seed)
    fake = Faker("en_US")

    os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
    if os.path.exists(args.db):
        os.remove(args.db)
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    with open(args.schema, encoding="utf-8") as f:
        conn.executescript(f.read())
    cur = conn.cursor()

    # 1. vehicle_category ----------------------------------------------------
    cur.executemany(
        "INSERT INTO vehicle_category (category_id, category_name, standard_daily_rate_cents) "
        "VALUES (?, ?, ?)",
        [(i, name, rate) for i, (name, rate) in enumerate(CATEGORIES, start=1)],
    )

    # 2. customer --------------------------------------------------------------
    customers = []
    for cid in range(1, NUM_CUSTOMERS + 1):
        first, last = fake.first_name(), fake.last_name()
        customers.append((
            cid,
            f"{first} {last}",
            f"{first.lower()}.{last.lower()}{cid}@{fake.free_email_domain()}",
            fake.numerify("(###) ###-####"),
            f"LA{fake.unique.numerify('########')}",
        ))
    cur.executemany(
        "INSERT INTO customer (customer_id, full_name, email, phone, driver_license_no) "
        "VALUES (?, ?, ?, ?, ?)", customers)

    # Some customers rent often, some rarely, a few never (0..* participation)
    customer_weights = [0.15 + random.random() ** 2 for _ in customers]
    for i in random.sample(range(NUM_CUSTOMERS), 8):
        customer_weights[i] = 0.0

    # 3. vehicle (+ build each vehicle's rental/maintenance timeline) ---------
    # Spread the fleet: more economy/compact/midsize cars than luxury ones
    fleet_mix = random.choices(range(1, len(CATEGORIES) + 1), weights=[6, 7, 7, 6, 3], k=NUM_VEHICLES)
    used_vins, used_plates = set(), set()
    all_rentals, all_jobs = [], []

    for vid, cat_id in enumerate(fleet_mix, start=1):
        cat_name, std_rate = CATEGORIES[cat_id - 1]
        make, model = random.choice(MODELS[cat_name])
        year = random.randint(2019, 2026)
        start_km = max(0, (2025 - year)) * random.randint(12000, 22000) + random.randint(50, 3000)

        rentals, jobs, km = build_timeline(std_rate)
        cur.execute(
            "INSERT INTO vehicle (vehicle_id, category_id, vin, registration_no, make, model, "
            "model_year, odometer_km) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (vid, cat_id, make_vin(used_vins), make_plate(used_plates),
             make, model, year, start_km + km))

        for r in rentals:
            r["vehicle_id"] = vid
        for j in jobs:
            j["vehicle_id"] = vid
        all_rentals.extend(rentals)
        all_jobs.extend(jobs)

    # 4. rental (inserted in pickup order so rental_id is chronological) -------
    all_rentals.sort(key=lambda r: r["pickup_at"])
    payments = []
    for rid, r in enumerate(all_rentals, start=1):
        cust_id = random.choices(range(1, NUM_CUSTOMERS + 1), weights=customer_weights)[0]
        cur.execute(
            "INSERT INTO rental (rental_id, customer_id, vehicle_id, pickup_at, due_at, "
            "returned_at, agreed_daily_rate_cents, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, cust_id, r["vehicle_id"], ts(r["pickup_at"]), ts(r["due_at"]),
             ts(r["returned_at"]), r["agreed_daily_rate_cents"], r["status"]))

        # 5. payments for this rental (0..* per rental) ------------------------
        method = random.choice(PAYMENT_METHODS)
        rate = r["agreed_daily_rate_cents"]
        if r["status"] == "completed":
            total = days_charged(r["pickup_at"], r["returned_at"]) * rate
            if random.random() < 0.35:   # deposit at pickup + balance at return
                deposit = max(100, int(total * 0.3) // 100 * 100)
                payments.append((rid, deposit, ts(r["pickup_at"]), method))
                payments.append((rid, total - deposit, ts(r["returned_at"]), method))
            else:                        # paid in full at return
                payments.append((rid, total, ts(r["returned_at"]), method))
        elif r["status"] == "active" and random.random() < 0.7:
            planned = days_charged(r["pickup_at"], r["due_at"]) * rate
            payments.append((rid, max(100, int(planned * 0.3) // 100 * 100),
                             ts(r["pickup_at"]), method))

    cur.executemany(
        "INSERT INTO payment (rental_id, amount_cents, paid_at, method) VALUES (?, ?, ?, ?)",
        sorted(payments, key=lambda p: p[2]))

    # 6. maintenance -------------------------------------------------------------
    all_jobs.sort(key=lambda j: j["started_at"])
    cur.executemany(
        "INSERT INTO maintenance (vehicle_id, service_type, started_at, completed_at, cost_cents) "
        "VALUES (?, ?, ?, ?, ?)",
        [(j["vehicle_id"], j["service_type"], ts(j["started_at"]), ts(j["completed_at"]),
          j["cost_cents"]) for j in all_jobs])

    conn.commit()

    # Sanity checks ---------------------------------------------------------------
    problems = conn.execute("PRAGMA foreign_key_check").fetchall()
    if problems:
        raise SystemExit(f"Foreign key violations: {problems}")

    print(f"Created {args.db} (seed={args.seed}, today={ts(NOW)})")
    for table in ["vehicle_category", "customer", "vehicle", "rental", "payment", "maintenance"]:
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<17} {n:>5} rows")
    print("  rental status:   " + ", ".join(
        f"{s}={n}" for s, n in conn.execute(
            "SELECT status, COUNT(*) FROM rental GROUP BY status ORDER BY status")))
    conn.close()


if __name__ == "__main__":
    main()
