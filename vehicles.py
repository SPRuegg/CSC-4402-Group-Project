from db import get_db, transaction
from datetime import datetime

FIELDS = (
    "category_id",
    "vin",
    "registration_no",
    "make",
    "model",
    "model_year",
    "odometer_km",
)

TEXT_LABELS = {
    "vin": "VIN",
    "registration_no": "Registration number",
    "make": "Make",
    "model": "Model",
}

# Keep JSON numbers exact when consumed by JavaScript.
MAX_SAFE_INTEGER = 9007199254740991


class VehicleValidationError(ValueError):
    pass


class VehicleNotFoundError(LookupError):
    pass


def list_vehicles():
    rows = get_db().execute(
        """
        SELECT v.*, c.category_name, c.standard_daily_rate_cents
        FROM vehicle AS v
        JOIN vehicle_category AS c ON c.category_id = v.category_id
        ORDER BY v.make, v.model, v.vehicle_id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_vehicle(vehicle_id):
    row = get_db().execute(
        """
        SELECT v.*, c.category_name, c.standard_daily_rate_cents
        FROM vehicle AS v
        JOIN vehicle_category AS c ON c.category_id = v.category_id
        WHERE v.vehicle_id = ?
        """,
        (vehicle_id,),
    ).fetchone()

    if row is None:
        raise VehicleNotFoundError("Vehicle not found.")

    return dict(row)


def _validate(data):
    if not isinstance(data, dict):
        raise VehicleValidationError(
            "Vehicle details must be an object."
        )

    values = {}

    for field, label in TEXT_LABELS.items():
        value = data.get(field)

        if not isinstance(value, str) or not value.strip():
            raise VehicleValidationError(f"{label} is required.")

        if "\x00" in value:
            raise VehicleValidationError(
                f"{label} contains an invalid character."
            )

        values[field] = value.strip()

    limits = {
        "category_id": (1, MAX_SAFE_INTEGER, "Category ID"),
        "model_year": (1980, 2100, "Model year"),
        "odometer_km": (0, MAX_SAFE_INTEGER, "Odometer"),
    }

    for field, (minimum, maximum, label) in limits.items():
        value = data.get(field)

        if type(value) is not int or not minimum <= value <= maximum:
            raise VehicleValidationError(
                f"{label} must be an integer between "
                f"{minimum} and {maximum}."
            )

        values[field] = value

    return values


def _check_category(connection, category_id):
    row = connection.execute(
        "SELECT 1 FROM vehicle_category WHERE category_id = ?",
        (category_id,),
    ).fetchone()

    if row is None:
        raise VehicleValidationError(
            "Select an existing vehicle category."
        )


def _check_duplicates(connection, values, vehicle_id=None):
    for field in ("vin", "registration_no"):
        row = connection.execute(
            f"""
            SELECT vehicle_id
            FROM vehicle
            WHERE {field} = ?
              AND (? IS NULL OR vehicle_id != ?)
            """,
            (values[field], vehicle_id, vehicle_id),
        ).fetchone()

        if row is not None:
            raise VehicleValidationError(
                f"{TEXT_LABELS[field]} is already in use."
            )


def create_vehicle(data):
    values = _validate(data)

    with transaction() as connection:
        _check_category(connection, values["category_id"])
        _check_duplicates(connection, values)

        cursor = connection.execute(
            """
            INSERT INTO vehicle (
                category_id, vin, registration_no,
                make, model, model_year, odometer_km
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(values[field] for field in FIELDS),
        )
        vehicle_id = cursor.lastrowid

    return get_vehicle(vehicle_id)


def update_vehicle(vehicle_id, data):
    values = _validate(data)

    with transaction() as connection:
        existing = get_vehicle(vehicle_id)

        if values["odometer_km"] < existing["odometer_km"]:
            raise VehicleValidationError(
                "Odometer reading cannot decrease."
            )

        _check_category(connection, values["category_id"])
        _check_duplicates(connection, values, vehicle_id)

        connection.execute(
            """
            UPDATE vehicle
            SET category_id = ?, vin = ?, registration_no = ?,
                make = ?, model = ?, model_year = ?, odometer_km = ?
            WHERE vehicle_id = ?
            """,
            (
                *[values[field] for field in FIELDS],
                vehicle_id,
            ),
        )

    return get_vehicle(vehicle_id)


def delete_vehicle(vehicle_id):
    with transaction() as connection:
        get_vehicle(vehicle_id)

        has_rentals = connection.execute(
            "SELECT 1 FROM rental WHERE vehicle_id = ? LIMIT 1",
            (vehicle_id,),
        ).fetchone()

        has_maintenance = connection.execute(
            "SELECT 1 FROM maintenance WHERE vehicle_id = ? LIMIT 1",
            (vehicle_id,),
        ).fetchone()

        if has_rentals is not None or has_maintenance is not None:
            raise VehicleValidationError(
                "Vehicles with rental or maintenance history "
                "cannot be deleted."
            )

        connection.execute(
            "DELETE FROM vehicle WHERE vehicle_id = ?",
            (vehicle_id,),
        )
def _validate_timestamp(value, label):
    if not isinstance(value, str):
        raise VehicleValidationError(
            f"{label} must use YYYY-MM-DD HH:MM:SS in UTC."
        )

    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise VehicleValidationError(
            f"{label} must be a valid UTC date and time "
            "using YYYY-MM-DD HH:MM:SS."
        ) from None

    if parsed.strftime("%Y-%m-%d %H:%M:%S") != value:
        raise VehicleValidationError(
            f"{label} must use YYYY-MM-DD HH:MM:SS."
        )

    return parsed


def get_vehicle_availability(
    vehicle_id, pickup_at, due_at, exclude_rental_id=None
):
    pickup = _validate_timestamp(pickup_at, "Pickup time")
    due = _validate_timestamp(due_at, "Due time")

    if due <= pickup:
        raise VehicleValidationError(
            "Due time must be after pickup time."
        )

    if exclude_rental_id is not None:
        if (
            type(exclude_rental_id) is not int
            or not 1 <= exclude_rental_id <= MAX_SAFE_INTEGER
        ):
            raise VehicleValidationError(
                "Excluded rental ID must be a positive integer."
            )

    get_vehicle(vehicle_id)
    connection = get_db()

    conflicts = connection.execute(
        """
        SELECT rental_id
        FROM rental
        WHERE vehicle_id = ?
          AND status != 'cancelled'
          AND (? IS NULL OR rental_id != ?)
          AND pickup_at < ?
          AND (
              CASE
                  WHEN status = 'completed' THEN returned_at
                  WHEN status = 'active' AND returned_at > due_at
                      THEN returned_at
                  ELSE due_at
              END
          ) > ?
        ORDER BY pickup_at, rental_id
        """,
        (
            vehicle_id,
            exclude_rental_id,
            exclude_rental_id,
            due_at,
            pickup_at,
        ),
    ).fetchall()

    active_rental = connection.execute(
        """
        SELECT rental_id
        FROM rental
        WHERE vehicle_id = ?
          AND status = 'active'
          AND (? IS NULL OR rental_id != ?)
        LIMIT 1
        """,
        (vehicle_id, exclude_rental_id, exclude_rental_id),
    ).fetchone()

    maintenance = connection.execute(
        """
        SELECT maintenance_id
        FROM maintenance
        WHERE vehicle_id = ?
          AND completed_at IS NULL
        LIMIT 1
        """,
        (vehicle_id,),
    ).fetchone()

    return {
        "vehicle_id": vehicle_id,
        "pickup_at": pickup_at,
        "due_at": due_at,
        "available_for_reservation": len(conflicts) == 0,
        "conflicting_rental_ids": [
            row["rental_id"] for row in conflicts
        ],
        "other_active_rental_id": (
            active_rental["rental_id"]
            if active_rental is not None
            else None
        ),
        "unfinished_maintenance_id": (
            maintenance["maintenance_id"]
            if maintenance is not None
            else None
        ),
    }