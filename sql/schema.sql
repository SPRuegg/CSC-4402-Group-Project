-- Car-rental SQLite database schema
--   * Monetary amounts are stored as INTEGER cents.
--   * Timestamps are stored as UTC TEXT in 'YYYY-MM-DD HH:MM:SS' format.
--   * SQLite disables foreign-key enforcement per connection by default;
--     enable it whenever executing this script or opening the database.

PRAGMA foreign_keys = ON;

CREATE TABLE customer (
    customer_id INTEGER PRIMARY KEY,
    full_name TEXT,
    email TEXT,
    phone TEXT,
    driver_license_no TEXT
);

CREATE TABLE vehicle_category (
    category_id INTEGER PRIMARY KEY,
    category_name TEXT,
    standard_daily_rate_cents INTEGER
);

CREATE TABLE vehicle (
    vehicle_id INTEGER PRIMARY KEY,
    category_id INTEGER,
    vin TEXT,
    registration_no TEXT,
    make TEXT,
    model TEXT,
    model_year INTEGER,
    odometer_km INTEGER,
    FOREIGN KEY (category_id) REFERENCES vehicle_category (category_id)
);

CREATE TABLE rental (
    rental_id INTEGER PRIMARY KEY,
    customer_id INTEGER,
    vehicle_id INTEGER,
    pickup_at TEXT,
    due_at TEXT,
    returned_at TEXT,
    agreed_daily_rate_cents INTEGER,
    status TEXT,
    FOREIGN KEY (customer_id) REFERENCES customer (customer_id),
    FOREIGN KEY (vehicle_id) REFERENCES vehicle (vehicle_id)
);

CREATE TABLE payment (
    payment_id INTEGER PRIMARY KEY,
    rental_id INTEGER,
    amount_cents INTEGER,
    paid_at TEXT,
    method TEXT,
    FOREIGN KEY (rental_id) REFERENCES rental (rental_id)
);

CREATE TABLE maintenance (
    maintenance_id INTEGER PRIMARY KEY,
    vehicle_id INTEGER,
    service_type TEXT,
    started_at TEXT,
    completed_at TEXT,
    cost_cents INTEGER,
    FOREIGN KEY (vehicle_id) REFERENCES vehicle (vehicle_id)
);
