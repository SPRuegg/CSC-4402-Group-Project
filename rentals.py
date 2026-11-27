from datetime import datetime, timezone

from db import get_db, transaction
import vehicles


MAX_SAFE_INTEGER = 9007199254740991
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

RESERVATION_FIELDS = {
    "customer_id", "vehicle_id", "pickup_at", "due_at"
}

RENTAL_SELECT = """
    SELECT r.*, c.full_name AS customer_name,
           v.make, v.model, v.model_year, v.registration_no
    FROM rental AS r
    JOIN customer AS c ON c.customer_id = r.customer_id
    JOIN vehicle AS v ON v.vehicle_id = r.vehicle_id
"""


class RentalValidationError(ValueError):
    pass


class RentalNotFoundError(LookupError):
    pass


def list_rentals():
    rows = get_db().execute(
        RENTAL_SELECT + " ORDER BY r.pickup_at DESC, r.rental_id DESC"
    ).fetchall()
    return [dict(row) for row in rows]


def get_rental(rental_id):
    row = get_db().execute(
        RENTAL_SELECT + " WHERE r.rental_id = ?",
        (rental_id,),
    ).fetchone()

    if row is None:
        raise RentalNotFoundError("Rental not found.")

    return dict(row)


def _positive_integer(value, label):
    if type(value) is not int or not 1 <= value <= MAX_SAFE_INTEGER:
        raise RentalValidationError(
            f"{label} must be a positive integer "
            "within the supported range."
        )
    return value


def _timestamp(value, label):
    if not isinstance(value, str):
        raise RentalValidationError(
            f"{label} must use YYYY-MM-DD HH:MM:SS in UTC."
        )

    try:
        parsed = datetime.strptime(value, TIMESTAMP_FORMAT)
    except ValueError:
        raise RentalValidationError(
            f"{label} must be a valid UTC date and time "
            "using YYYY-MM-DD HH:MM:SS."
        ) from None

    if parsed.strftime(TIMESTAMP_FORMAT) != value:
        raise RentalValidationError(
            f"{label} must use YYYY-MM-DD HH:MM:SS."
        )

    return parsed


def _validate_reservation(data):
    if not isinstance(data, dict):
        raise RentalValidationError(
            "Reservation details must be an object."
        )

    unexpected = set(data) - RESERVATION_FIELDS
    if unexpected:
        raise RentalValidationError(
            "Unsupported reservation fields: "
            + ", ".join(sorted(unexpected))
        )

    values = {
        "customer_id": _positive_integer(
            data.get("customer_id"), "Customer ID"
        ),
        "vehicle_id": _positive_integer(
            data.get("vehicle_id"), "Vehicle ID"
        ),
        "pickup_at": data.get("pickup_at"),
        "due_at": data.get("due_at"),
    }

    pickup = _timestamp(values["pickup_at"], "Pickup time")
    due = _timestamp(values["due_at"], "Due time")

    if due <= pickup:
        raise RentalValidationError(
            "Due time must be after pickup time."
        )

    return values


def _check_customer(connection, customer_id):
    row = connection.execute(
        "SELECT 1 FROM customer WHERE customer_id = ?",
        (customer_id,),
    ).fetchone()

    if row is None:
        raise RentalValidationError("Select an existing customer.")


def _check_availability(values, exclude_rental_id=None):
    try:
        availability = vehicles.get_vehicle_availability(
            values["vehicle_id"],
            values["pickup_at"],
            values["due_at"],
            exclude_rental_id=exclude_rental_id,
        )
    except (
        vehicles.VehicleValidationError,
        vehicles.VehicleNotFoundError,
    ) as error:
        raise RentalValidationError(str(error)) from None

    if not availability["available_for_reservation"]:
        raise RentalValidationError(
            "This vehicle has a conflicting rental "
            "during the selected period."
        )

    return availability


def create_reservation(data):
    values = _validate_reservation(data)

    with transaction() as connection:
        _check_customer(connection, values["customer_id"])
        _check_availability(values)

        vehicle = vehicles.get_vehicle(values["vehicle_id"])
        rate = _positive_integer(
            vehicle["standard_daily_rate_cents"], "Daily rate"
        )

        cursor = connection.execute(
            """
            INSERT INTO rental (
                customer_id, vehicle_id, pickup_at, due_at,
                agreed_daily_rate_cents, status
            )
            VALUES (?, ?, ?, ?, ?, 'reserved')
            """,
            (
                values["customer_id"],
                values["vehicle_id"],
                values["pickup_at"],
                values["due_at"],
                rate,
            ),
        )
        rental_id = cursor.lastrowid

    return get_rental(rental_id)

def _require_reserved(rental):
    if rental["status"] != "reserved":
        raise RentalValidationError(
            "This operation is allowed only for reserved rentals."
        )


def update_reservation(rental_id, data):
    if not isinstance(data, dict):
        raise RentalValidationError(
            "Reservation details must be an object."
        )

    # An agreed rate can be explicitly changed while reserved.
    details = dict(data)
    has_rate = "agreed_daily_rate_cents" in details
    rate = details.pop("agreed_daily_rate_cents", None)
    values = _validate_reservation(details)

    if has_rate:
        rate = _positive_integer(rate, "Agreed daily rate")

    with transaction() as connection:
        rental = get_rental(rental_id)
        _require_reserved(rental)
        _check_customer(connection, values["customer_id"])
        _check_availability(values, exclude_rental_id=rental_id)

        # Preserve the original agreement unless explicitly edited.
        if not has_rate:
            rate = rental["agreed_daily_rate_cents"]

        connection.execute(
            """
            UPDATE rental
            SET customer_id = ?, vehicle_id = ?,
                pickup_at = ?, due_at = ?,
                agreed_daily_rate_cents = ?
            WHERE rental_id = ?
            """,
            (
                values["customer_id"],
                values["vehicle_id"],
                values["pickup_at"],
                values["due_at"],
                rate,
                rental_id,
            ),
        )

    return get_rental(rental_id)


def cancel_reservation(rental_id):
    with transaction() as connection:
        rental = get_rental(rental_id)
        _require_reserved(rental)

        connection.execute(
            "UPDATE rental SET status = 'cancelled' WHERE rental_id = ?",
            (rental_id,),
        )

    return get_rental(rental_id)


def _utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def pickup_reservation(rental_id):
    with transaction() as connection:
        rental = get_rental(rental_id)
        _require_reserved(rental)

        pickup = _timestamp(rental["pickup_at"], "Pickup time")
        due = _timestamp(rental["due_at"], "Due time")
        now = _utc_now()

        if now < pickup:
            raise RentalValidationError(
                "Pickup is not allowed before the agreed pickup time."
            )

        if now >= due:
            raise RentalValidationError(
                "This reservation has expired. "
                "Edit or cancel it before pickup."
            )

        availability = _check_availability(
            rental, exclude_rental_id=rental_id
        )

        if availability["other_active_rental_id"] is not None:
            raise RentalValidationError(
                "This vehicle has another active rental. "
                "It must be returned and completed before pickup."
            )

        if availability["unfinished_maintenance_id"] is not None:
            raise RentalValidationError(
                "This vehicle has unfinished maintenance "
                "and cannot be picked up."
            )

        connection.execute(
            "UPDATE rental SET status = 'active' WHERE rental_id = ?",
            (rental_id,),
        )

    return get_rental(rental_id)


def delete_reservation(rental_id):
    with transaction() as connection:
        rental = get_rental(rental_id)
        _require_reserved(rental)

        has_payments = connection.execute(
            "SELECT 1 FROM payment WHERE rental_id = ? LIMIT 1",
            (rental_id,),
        ).fetchone()

        if has_payments is not None:
            raise RentalValidationError(
                "Reservations with payments cannot be deleted."
            )

        connection.execute(
            "DELETE FROM rental WHERE rental_id = ?",
            (rental_id,),
        )