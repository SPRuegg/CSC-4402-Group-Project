import sqlite3

from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import (
    BadRequest,
    RequestEntityTooLarge,
    UnsupportedMediaType,
)

import billing
import rentals


bp = Blueprint("billing", __name__, url_prefix="/api/rentals")


@bp.before_request
def limit_request_size():
    request.max_content_length = 64 * 1024


@bp.errorhandler(billing.BillingValidationError)
def invalid_billing(error):
    return jsonify(error=str(error)), 400


@bp.errorhandler(billing.PaymentNotFoundError)
@bp.errorhandler(rentals.RentalNotFoundError)
def missing_record(error):
    return jsonify(error=str(error)), 404


@bp.errorhandler(BadRequest)
def invalid_json(error):
    return jsonify(error="Request body must contain valid JSON."), 400


@bp.errorhandler(UnsupportedMediaType)
def unsupported_content_type(error):
    return jsonify(
        error="Send billing details as application/json."
    ), 415


@bp.errorhandler(RequestEntityTooLarge)
def oversized_request(error):
    return jsonify(
        error="Billing details exceed the request size limit."
    ), 413


@bp.errorhandler(sqlite3.DatabaseError)
def database_error(error):
    current_app.logger.exception("Billing database operation failed")
    return jsonify(
        error="Unable to save or load billing records. Please try again."
    ), 500


def _return_time():
    data = request.get_json()

    if not isinstance(data, dict) or set(data) != {"returned_at"}:
        raise billing.BillingValidationError(
            "Provide an object containing only returned_at."
        )

    return data["returned_at"]


@bp.get("/<int:rental_id>/statement")
def get_statement(rental_id):
    return jsonify(statement=billing.get_statement(rental_id))


@bp.post("/<int:rental_id>/payments")
def create_payment(rental_id):
    payment = billing.create_payment(
        rental_id, request.get_json()
    )

    response = jsonify(
        payment=payment,
        message="Payment recorded.",
    )
    response.status_code = 201
    response.headers["Location"] = (
        f"/api/rentals/{rental_id}/payments/{payment['payment_id']}"
    )
    return response


@bp.get("/<int:rental_id>/payments/<int:payment_id>")
def get_payment(rental_id, payment_id):
    statement = billing.get_statement(rental_id)

    payment = next(
        (
            item for item in statement["payments"]
            if item["payment_id"] == payment_id
        ),
        None,
    )

    if payment is None:
        raise billing.PaymentNotFoundError(
            "Payment not found for this rental."
        )

    return jsonify(payment=payment)


@bp.put("/<int:rental_id>/payments/<int:payment_id>")
def update_payment(rental_id, payment_id):
    payment = billing.update_payment(
        rental_id, payment_id, request.get_json()
    )
    return jsonify(payment=payment, message="Payment updated.")


@bp.delete("/<int:rental_id>/payments/<int:payment_id>")
def delete_payment(rental_id, payment_id):
    billing.delete_payment(rental_id, payment_id)
    return jsonify(message="Payment deleted.")


@bp.post("/<int:rental_id>/return-preview")
def preview_return(rental_id):
    statement = billing.preview_return(rental_id, _return_time())
    return jsonify(statement=statement)


@bp.post("/<int:rental_id>/return")
def record_return(rental_id):
    statement = billing.record_return(rental_id, _return_time())
    return jsonify(
        statement=statement,
        message="Return recorded. Settle the balance before completion.",
    )


@bp.post("/<int:rental_id>/complete")
def complete_return(rental_id):
    statement = billing.complete_return(rental_id)
    return jsonify(
        statement=statement,
        message="Rental completed.",
    )