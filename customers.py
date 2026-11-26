from db import get_db, transaction


FIELDS = ("full_name", "email", "phone", "driver_license_no")
LABELS = {
    "full_name": "Name",
    "email": "Email",
    "phone": "Phone",
    "driver_license_no": "Driver-license number",
}


class CustomerValidationError(ValueError):
    pass


class CustomerNotFoundError(LookupError):
    pass


def list_customers():
    rows = get_db().execute(
        "SELECT customer_id, full_name, email, phone, driver_license_no "
        "FROM customer ORDER BY full_name, customer_id"
    ).fetchall()
    return [dict(row) for row in rows]


def get_customer(customer_id):
    row = get_db().execute(
        "SELECT customer_id, full_name, email, phone, driver_license_no "
        "FROM customer WHERE customer_id = ?", (customer_id,)
    ).fetchone()
    if row is None:
        raise CustomerNotFoundError("Customer not found.")
    return dict(row)


def _validate(data):
    if not isinstance(data, dict):
        raise CustomerValidationError("Customer details must be an object.")
    values = {}
    for field in FIELDS:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            raise CustomerValidationError(f"{LABELS[field]} is required.")
        if "\x00" in value:
            raise CustomerValidationError(f"{LABELS[field]} contains an invalid character.")
        values[field] = value.strip()
    return values


def _check_duplicates(connection, values, customer_id=None):
    for field in ("email", "driver_license_no"):
        row = connection.execute(
            f"SELECT customer_id FROM customer WHERE {field} = ? "
            "AND (? IS NULL OR customer_id != ?)",
            (values[field], customer_id, customer_id),
        ).fetchone()
        if row is not None:
            raise CustomerValidationError(f"{LABELS[field]} is already in use.")


def create_customer(data):
    values = _validate(data)
    with transaction() as connection:
        _check_duplicates(connection, values)
        cursor = connection.execute(
            "INSERT INTO customer (full_name, email, phone, driver_license_no) "
            "VALUES (?, ?, ?, ?)", tuple(values[field] for field in FIELDS)
        )
        customer_id = cursor.lastrowid
    return get_customer(customer_id)


def update_customer(customer_id, data):
    values = _validate(data)
    with transaction() as connection:
        get_customer(customer_id)
        _check_duplicates(connection, values, customer_id)
        connection.execute(
            "UPDATE customer SET full_name = ?, email = ?, phone = ?, "
            "driver_license_no = ? WHERE customer_id = ?",
            (*[values[field] for field in FIELDS], customer_id),
        )
    return get_customer(customer_id)


def delete_customer(customer_id):
    with transaction() as connection:
        get_customer(customer_id)
        referenced = connection.execute(
            "SELECT 1 FROM rental WHERE customer_id = ? LIMIT 1", (customer_id,)
        ).fetchone()
        if referenced is not None:
            raise CustomerValidationError(
                "Customers with rental history cannot be deleted."
            )
        connection.execute(
            "DELETE FROM customer WHERE customer_id = ?", (customer_id,)
        )
