from datetime import datetime, timezone

from db import get_db, transaction
import rentals


MAX_SAFE_INTEGER = 9007199254740991
SECONDS_PER_DAY = 86400
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


class BillingValidationError(ValueError):
    pass


class PaymentNotFoundError(LookupError):
    pass


def _timestamp(value, label):
    if not isinstance(value, str):
        raise BillingValidationError(
            f"{label} must use YYYY-MM-DD HH:MM:SS in UTC."
        )

    try:
        parsed = datetime.strptime(value, TIMESTAMP_FORMAT)
    except ValueError:
        raise BillingValidationError(
            f"{label} must be a valid UTC date and time "
            "using YYYY-MM-DD HH:MM:SS."
        ) from None

    if parsed.strftime(TIMESTAMP_FORMAT) != value:
        raise BillingValidationError(
            f"{label} must use YYYY-MM-DD HH:MM:SS."
        )

    return parsed


def _positive_integer(value, label):
    if type(value) is not int or not 1 <= value <= MAX_SAFE_INTEGER:
        raise BillingValidationError(
            f"{label} must be a positive integer "
            "within the supported range."
        )
    return value


def calculate_charge(rental, returned_at=None):
    if rental["status"] == "cancelled":
        if returned_at is not None:
            raise BillingValidationError(
                "Cancelled rentals cannot have a return time."
            )

        return {
            "charge_type": "cancelled",
            "billed_days": 0,
            "charge_cents": 0,
            "billing_end_at": None,
        }

    pickup = _timestamp(rental["pickup_at"], "Pickup time")
    due = _timestamp(rental["due_at"], "Due time")

    if due <= pickup:
        raise BillingValidationError(
            "Due time must be after pickup time."
        )

    rate = _positive_integer(
        rental["agreed_daily_rate_cents"], "Agreed daily rate"
    )

    actual_return = (
        returned_at
        if returned_at is not None
        else rental["returned_at"]
    )

    if actual_return is None:
        billing_end = due
        charge_type = "quote"
    else:
        returned = _timestamp(actual_return, "Return time")

        if returned <= pickup:
            raise BillingValidationError(
                "Return time must be after pickup time."
            )

        billing_end = max(due, returned)
        charge_type = "final"

    duration = billing_end - pickup
    seconds = duration.days * SECONDS_PER_DAY + duration.seconds

    billed_days = max(
        1,
        (seconds + SECONDS_PER_DAY - 1) // SECONDS_PER_DAY,
    )
    charge = billed_days * rate

    if charge > MAX_SAFE_INTEGER:
        raise BillingValidationError(
            "Calculated charge exceeds the supported range."
        )

    return {
        "charge_type": charge_type,
        "billed_days": billed_days,
        "charge_cents": charge,
        "billing_end_at": billing_end.strftime(TIMESTAMP_FORMAT),
    }


def _build_statement(connection, rental, returned_at=None):
    charge = calculate_charge(rental, returned_at=returned_at)

    rows = connection.execute(
        """
        SELECT payment_id, rental_id, amount_cents, paid_at, method
        FROM payment
        WHERE rental_id = ?
        ORDER BY paid_at, payment_id
        """,
        (rental["rental_id"],),
    ).fetchall()

    payments = [dict(row) for row in rows]
    paid = sum(payment["amount_cents"] for payment in payments)

    if paid > MAX_SAFE_INTEGER:
        raise BillingValidationError(
            "Total payments exceed the supported range."
        )

    return {
        "rental": rental,
        **charge,
        "payments": payments,
        "paid_cents": paid,
        "balance_cents": charge["charge_cents"] - paid,
        "affected_reservation_ids": _affected_reservations(
            connection, rental, returned_at=returned_at
        ),
    }


def get_statement(rental_id):
    with transaction() as connection:
        rental = rentals.get_rental(rental_id)
        statement = _build_statement(connection, rental)

    return statement

PAYMENT_FIELDS = {"amount_cents", "paid_at", "method"}


def _require_active(rental):
    if rental["status"] != "active":
        raise BillingValidationError(
            "Payments and returns can be changed only "
            "while the rental is active."
        )


def _validate_payment(data):
    if not isinstance(data, dict):
        raise BillingValidationError(
            "Payment details must be an object."
        )

    unexpected = set(data) - PAYMENT_FIELDS
    if unexpected:
        raise BillingValidationError(
            "Unsupported payment fields: "
            + ", ".join(sorted(unexpected))
        )

    amount = _positive_integer(
        data.get("amount_cents"), "Payment amount"
    )
    paid_at = data.get("paid_at")
    _timestamp(paid_at, "Payment time")

    method = data.get("method")
    if method not in ("cash", "card", "transfer"):
        raise BillingValidationError(
            "Payment method must be cash, card, or transfer."
        )

    return {
        "amount_cents": amount,
        "paid_at": paid_at,
        "method": method,
    }


def _check_payment_time(rental, paid_at):
    paid = _timestamp(paid_at, "Payment time")
    pickup = _timestamp(rental["pickup_at"], "Pickup time")

    if paid < pickup:
        raise BillingValidationError(
            "Payment time cannot be before pickup."
        )

    if rental["returned_at"] is not None:
        returned = _timestamp(rental["returned_at"], "Return time")

        if paid > returned:
            raise BillingValidationError(
                "Payment time cannot be after the recorded return."
            )


def _get_payment(connection, rental_id, payment_id):
    row = connection.execute(
        """
        SELECT payment_id, rental_id, amount_cents, paid_at, method
        FROM payment
        WHERE rental_id = ? AND payment_id = ?
        """,
        (rental_id, payment_id),
    ).fetchone()

    if row is None:
        raise PaymentNotFoundError(
            "Payment not found for this rental."
        )

    return dict(row)


def _reject_overpayment(connection, rental):
    statement = _build_statement(connection, rental)

    if statement["balance_cents"] < 0:
        raise BillingValidationError(
            "Total payments cannot exceed the rental charge."
        )


def create_payment(rental_id, data):
    values = _validate_payment(data)

    with transaction() as connection:
        rental = rentals.get_rental(rental_id)
        _require_active(rental)
        _check_payment_time(rental, values["paid_at"])

        cursor = connection.execute(
            """
            INSERT INTO payment (
                rental_id, amount_cents, paid_at, method
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                rental_id,
                values["amount_cents"],
                values["paid_at"],
                values["method"],
            ),
        )

        _reject_overpayment(connection, rental)
        payment = _get_payment(
            connection, rental_id, cursor.lastrowid
        )

    return payment


def update_payment(rental_id, payment_id, data):
    values = _validate_payment(data)

    with transaction() as connection:
        rental = rentals.get_rental(rental_id)
        _require_active(rental)
        _get_payment(connection, rental_id, payment_id)
        _check_payment_time(rental, values["paid_at"])

        connection.execute(
            """
            UPDATE payment
            SET amount_cents = ?, paid_at = ?, method = ?
            WHERE rental_id = ? AND payment_id = ?
            """,
            (
                values["amount_cents"],
                values["paid_at"],
                values["method"],
                rental_id,
                payment_id,
            ),
        )

        _reject_overpayment(connection, rental)
        payment = _get_payment(connection, rental_id, payment_id)

    return payment


def delete_payment(rental_id, payment_id):
    with transaction() as connection:
        rental = rentals.get_rental(rental_id)
        _require_active(rental)
        _get_payment(connection, rental_id, payment_id)

        connection.execute(
            "DELETE FROM payment "
            "WHERE rental_id = ? AND payment_id = ?",
            (rental_id, payment_id),
        )

def _utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _validate_new_return(connection, rental, returned_at):
    _require_active(rental)

    if rental["returned_at"] is not None:
        raise BillingValidationError(
            "This rental already has a recorded return."
        )

    returned = _timestamp(returned_at, "Return time")
    pickup = _timestamp(rental["pickup_at"], "Pickup time")

    if returned <= pickup:
        raise BillingValidationError(
            "Return time must be after pickup time."
        )

    if returned > _utc_now():
        raise BillingValidationError(
            "An actual return cannot be recorded in the future."
        )

    later_payment = connection.execute(
        """
        SELECT 1
        FROM payment
        WHERE rental_id = ? AND paid_at > ?
        LIMIT 1
        """,
        (rental["rental_id"], returned_at),
    ).fetchone()

    if later_payment is not None:
        raise BillingValidationError(
            "Return time cannot be before an existing payment. "
            "Correct the payment time first."
        )


def _affected_reservations(connection, rental, returned_at=None):
    actual_return = (
        returned_at
        if returned_at is not None
        else rental["returned_at"]
    )

    if actual_return is None or actual_return <= rental["due_at"]:
        return []

    rows = connection.execute(
        """
        SELECT rental_id
        FROM rental
        WHERE vehicle_id = ?
          AND rental_id != ?
          AND status = 'reserved'
          AND pickup_at < ?
          AND due_at > ?
        ORDER BY pickup_at, rental_id
        """,
        (
            rental["vehicle_id"],
            rental["rental_id"],
            actual_return,
            rental["pickup_at"],
        ),
    ).fetchall()

    return [row["rental_id"] for row in rows]


def preview_return(rental_id, returned_at):
    with transaction() as connection:
        rental = rentals.get_rental(rental_id)
        _validate_new_return(connection, rental, returned_at)

        statement = _build_statement(
            connection, rental, returned_at=returned_at
        )
        statement["charge_type"] = "return_preview"

    return statement


def record_return(rental_id, returned_at):
    with transaction() as connection:
        rental = rentals.get_rental(rental_id)
        _validate_new_return(connection, rental, returned_at)

        statement = _build_statement(
            connection, rental, returned_at=returned_at
        )

        if statement["balance_cents"] < 0:
            raise BillingValidationError(
                "Recorded payments exceed the final charge."
            )

        connection.execute(
            "UPDATE rental SET returned_at = ? WHERE rental_id = ?",
            (returned_at, rental_id),
        )

        updated = rentals.get_rental(rental_id)
        statement = _build_statement(connection, updated)

    return statement


def complete_return(rental_id):
    with transaction() as connection:
        rental = rentals.get_rental(rental_id)
        _require_active(rental)

        if rental["returned_at"] is None:
            raise BillingValidationError(
                "Record the actual return before completing the rental."
            )

        statement = _build_statement(connection, rental)

        if statement["balance_cents"] != 0:
            raise BillingValidationError(
                "The final charge must be fully paid "
                "before completing the rental."
            )

        connection.execute(
            "UPDATE rental SET status = 'completed' WHERE rental_id = ?",
            (rental_id,),
        )

        updated = rentals.get_rental(rental_id)
        statement = _build_statement(connection, updated)

    return statement