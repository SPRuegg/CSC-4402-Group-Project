from db import get_db, transaction


class CategoryValidationError(ValueError):
    pass


class CategoryNotFoundError(LookupError):
    pass


def list_categories():
    rows = get_db().execute(
        """
        SELECT category_id, category_name, standard_daily_rate_cents
        FROM vehicle_category
        ORDER BY category_name, category_id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_category(category_id):
    row = get_db().execute(
        """
        SELECT category_id, category_name, standard_daily_rate_cents
        FROM vehicle_category
        WHERE category_id = ?
        """,
        (category_id,),
    ).fetchone()

    if row is None:
        raise CategoryNotFoundError("Category not found.")

    return dict(row)


def _validate(data):
    if not isinstance(data, dict):
        raise CategoryValidationError(
            "Category details must be an object."
        )

    name = data.get("category_name")
    rate = data.get("standard_daily_rate_cents")

    if not isinstance(name, str) or not name.strip():
        raise CategoryValidationError("Category name is required.")

    if "\x00" in name:
        raise CategoryValidationError(
            "Category name contains an invalid character."
        )

    if type(rate) is not int or not 0 < rate <= 9223372036854775807:
        raise CategoryValidationError(
            "Daily rate must be a positive integer in cents "
            "within SQLite's integer range."
        )

    return {
        "category_name": name.strip(),
        "standard_daily_rate_cents": rate,
    }


def _check_duplicate(connection, name, category_id=None):
    row = connection.execute(
        """
        SELECT category_id
        FROM vehicle_category
        WHERE category_name = ?
          AND (? IS NULL OR category_id != ?)
        """,
        (name, category_id, category_id),
    ).fetchone()

    if row is not None:
        raise CategoryValidationError(
            "Category name is already in use."
        )


def create_category(data):
    values = _validate(data)

    with transaction() as connection:
        _check_duplicate(connection, values["category_name"])

        cursor = connection.execute(
            """
            INSERT INTO vehicle_category (
                category_name, standard_daily_rate_cents
            )
            VALUES (?, ?)
            """,
            (
                values["category_name"],
                values["standard_daily_rate_cents"],
            ),
        )
        category_id = cursor.lastrowid

    return get_category(category_id)


def update_category(category_id, data):
    values = _validate(data)

    with transaction() as connection:
        get_category(category_id)
        _check_duplicate(
            connection, values["category_name"], category_id
        )

        connection.execute(
            """
            UPDATE vehicle_category
            SET category_name = ?, standard_daily_rate_cents = ?
            WHERE category_id = ?
            """,
            (
                values["category_name"],
                values["standard_daily_rate_cents"],
                category_id,
            ),
        )

    return get_category(category_id)


def delete_category(category_id):
    with transaction() as connection:
        get_category(category_id)

        referenced = connection.execute(
            "SELECT 1 FROM vehicle WHERE category_id = ? LIMIT 1",
            (category_id,),
        ).fetchone()

        if referenced is not None:
            raise CategoryValidationError(
                "Categories assigned to vehicles cannot be deleted."
            )

        connection.execute(
            "DELETE FROM vehicle_category WHERE category_id = ?",
            (category_id,),
        )