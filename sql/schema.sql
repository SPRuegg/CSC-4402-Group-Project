-- Car-rental SQLite database schema
--   * Monetary amounts are stored as INTEGER cents.
--   * Timestamps are stored as UTC TEXT in 'YYYY-MM-DD HH:MM:SS' format.
--   * SQLite disables foreign-key enforcement per connection by default;
--     enable it whenever executing this script or opening the database.

PRAGMA foreign_keys = ON;

CREATE TABLE customer (
    customer_id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL CHECK (length(trim(full_name, char(9, 10, 11, 12, 13, 32))) > 0),
    email TEXT NOT NULL UNIQUE CHECK (length(trim(email, char(9, 10, 11, 12, 13, 32))) > 0),
    phone TEXT NOT NULL CHECK (length(trim(phone, char(9, 10, 11, 12, 13, 32))) > 0),
    driver_license_no TEXT NOT NULL UNIQUE CHECK (length(trim(driver_license_no, char(9, 10, 11, 12, 13, 32))) > 0)
);

CREATE TABLE vehicle_category (
    category_id INTEGER PRIMARY KEY,
    category_name TEXT NOT NULL UNIQUE CHECK (length(trim(category_name, char(9, 10, 11, 12, 13, 32))) > 0),
    standard_daily_rate_cents INTEGER NOT NULL CHECK (
        typeof(standard_daily_rate_cents) = 'integer'
        AND standard_daily_rate_cents > 0
    )
);

CREATE TABLE vehicle (
    vehicle_id INTEGER PRIMARY KEY,
    category_id INTEGER NOT NULL,
    vin TEXT NOT NULL UNIQUE CHECK (length(trim(vin, char(9, 10, 11, 12, 13, 32))) > 0),
    registration_no TEXT NOT NULL UNIQUE CHECK (length(trim(registration_no, char(9, 10, 11, 12, 13, 32))) > 0),
    make TEXT NOT NULL CHECK (length(trim(make, char(9, 10, 11, 12, 13, 32))) > 0),
    model TEXT NOT NULL CHECK (length(trim(model, char(9, 10, 11, 12, 13, 32))) > 0),
    model_year INTEGER NOT NULL CHECK (
        typeof(model_year) = 'integer'
        AND model_year BETWEEN 1980 AND 2100
    ),
    odometer_km INTEGER NOT NULL CHECK (
        typeof(odometer_km) = 'integer'
        AND odometer_km >= 0
    ),
    FOREIGN KEY (category_id)
        REFERENCES vehicle_category (category_id)
        ON DELETE RESTRICT
);

CREATE TABLE rental (
    rental_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    vehicle_id INTEGER NOT NULL,
    pickup_at TEXT NOT NULL CHECK (
        pickup_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
        AND datetime(pickup_at) IS pickup_at
    ),
    due_at TEXT NOT NULL CHECK (
        due_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
        AND datetime(due_at) IS due_at
    ),
    returned_at TEXT CHECK (
        returned_at IS NULL
        OR (
            returned_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
            AND datetime(returned_at) IS returned_at
        )
    ),
    agreed_daily_rate_cents INTEGER NOT NULL CHECK (
        typeof(agreed_daily_rate_cents) = 'integer'
        AND agreed_daily_rate_cents > 0
    ),
    status TEXT NOT NULL CHECK (status IN ('reserved', 'active', 'completed', 'cancelled')),
    CHECK (due_at > pickup_at),
    CHECK (returned_at IS NULL OR returned_at > pickup_at),
    CHECK (
        (status IN ('reserved', 'cancelled') AND returned_at IS NULL)
        OR (status = 'completed' AND returned_at IS NOT NULL)
        OR status = 'active'
    ),
    FOREIGN KEY (customer_id)
        REFERENCES customer (customer_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (vehicle_id)
        REFERENCES vehicle (vehicle_id)
        ON DELETE RESTRICT
);

CREATE UNIQUE INDEX idx_rental_one_active_per_vehicle
    ON rental (vehicle_id)
    WHERE status = 'active';

CREATE TABLE payment (
    payment_id INTEGER PRIMARY KEY,
    rental_id INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (
        typeof(amount_cents) = 'integer'
        AND amount_cents > 0
    ),
    paid_at TEXT NOT NULL CHECK (
        paid_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
        AND datetime(paid_at) IS paid_at
    ),
    method TEXT NOT NULL CHECK (method IN ('cash', 'card', 'transfer')),
    FOREIGN KEY (rental_id)
        REFERENCES rental (rental_id)
        ON DELETE RESTRICT
);

CREATE TABLE maintenance (
    maintenance_id INTEGER PRIMARY KEY,
    vehicle_id INTEGER NOT NULL,
    service_type TEXT NOT NULL CHECK (length(trim(service_type, char(9, 10, 11, 12, 13, 32))) > 0),
    started_at TEXT NOT NULL CHECK (
        started_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
        AND datetime(started_at) IS started_at
    ),
    completed_at TEXT CHECK (
        completed_at IS NULL
        OR (
            completed_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
            AND datetime(completed_at) IS completed_at
        )
    ),
    cost_cents INTEGER NOT NULL CHECK (
        typeof(cost_cents) = 'integer'
        AND cost_cents >= 0
    ),
    CHECK (completed_at IS NULL OR completed_at >= started_at),
    FOREIGN KEY (vehicle_id)
        REFERENCES vehicle (vehicle_id)
        ON DELETE RESTRICT
);

CREATE UNIQUE INDEX idx_maintenance_one_open_per_vehicle
    ON maintenance (vehicle_id)
    WHERE completed_at IS NULL;
