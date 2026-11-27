import sqlite3

from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import (
    BadRequest,
    RequestEntityTooLarge,
    UnsupportedMediaType,
)

import rentals


bp = Blueprint("rentals", __name__, url_prefix="/api/rentals")


@bp.before_request
def limit_request_size():
    request.max_content_length = 64 * 1024


@bp.errorhandler(rentals.RentalValidationError)
def invalid_rental(error):
    return jsonify(error=str(error)), 400


@bp.errorhandler(rentals.RentalNotFoundError)
def missing_rental(error):
    return jsonify(error=str(error)), 404


@bp.errorhandler(BadRequest)
def invalid_json(error):
    return jsonify(error="Request body must contain valid JSON."), 400


@bp.errorhandler(UnsupportedMediaType)
def unsupported_content_type(error):
    return jsonify(
        error="Send reservation details as application/json."
    ), 415


@bp.errorhandler(RequestEntityTooLarge)
def oversized_request(error):
    return jsonify(
        error="Reservation details exceed the request size limit."
    ), 413


@bp.errorhandler(sqlite3.DatabaseError)
def database_error(error):
    current_app.logger.exception("Rental database operation failed")
    return jsonify(
        error="Unable to save or load rental records. Please try again."
    ), 500


@bp.get("")
def list_rentals():
    return jsonify(rentals=rentals.list_rentals())


@bp.get("/<int:rental_id>")
def get_rental(rental_id):
    return jsonify(rental=rentals.get_rental(rental_id))


@bp.post("")
def create_reservation():
    rental = rentals.create_reservation(request.get_json())
    response = jsonify(
        rental=rental,
        message="Reservation created.",
    )
    response.status_code = 201
    response.headers["Location"] = (
        f"/api/rentals/{rental['rental_id']}"
    )
    return response


@bp.put("/<int:rental_id>")
def update_reservation(rental_id):
    rental = rentals.update_reservation(
        rental_id, request.get_json()
    )
    return jsonify(rental=rental, message="Reservation updated.")


@bp.post("/<int:rental_id>/cancel")
def cancel_reservation(rental_id):
    rental = rentals.cancel_reservation(rental_id)
    return jsonify(rental=rental, message="Reservation cancelled.")


@bp.post("/<int:rental_id>/pickup")
def pickup_reservation(rental_id):
    rental = rentals.pickup_reservation(rental_id)
    return jsonify(rental=rental, message="Vehicle pickup recorded.")


@bp.delete("/<int:rental_id>")
def delete_reservation(rental_id):
    rentals.delete_reservation(rental_id)
    return jsonify(message="Reservation deleted.")