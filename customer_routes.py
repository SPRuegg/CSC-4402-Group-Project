import sqlite3

from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge, UnsupportedMediaType

import customers


bp = Blueprint("customers", __name__, url_prefix="/api/customers")


@bp.before_request
def limit_request_size():
    request.max_content_length = 64 * 1024


@bp.errorhandler(customers.CustomerValidationError)
def invalid_customer(error):
    return jsonify(error=str(error)), 400


@bp.errorhandler(customers.CustomerNotFoundError)
def missing_customer(error):
    return jsonify(error=str(error)), 404


@bp.errorhandler(BadRequest)
def invalid_json(error):
    return jsonify(error="Request body must contain valid JSON."), 400


@bp.errorhandler(UnsupportedMediaType)
def unsupported_content_type(error):
    return jsonify(error="Send customer details as application/json."), 415


@bp.errorhandler(RequestEntityTooLarge)
def oversized_request(error):
    return jsonify(error="Customer details exceed the request size limit."), 413


@bp.errorhandler(sqlite3.DatabaseError)
def database_error(error):
    current_app.logger.exception("Customer database operation failed")
    return jsonify(error="Unable to save or load customer records. Please try again."), 500


@bp.get("")
def list_customers():
    return jsonify(customers=customers.list_customers())


@bp.get("/<int:customer_id>")
def get_customer(customer_id):
    return jsonify(customer=customers.get_customer(customer_id))


@bp.post("")
def create_customer():
    customer = customers.create_customer(request.get_json())
    response = jsonify(customer=customer, message="Customer created.")
    response.status_code = 201
    response.headers["Location"] = f"{bp.url_prefix}/{customer['customer_id']}"
    return response


@bp.put("/<int:customer_id>")
def update_customer(customer_id):
    customer = customers.update_customer(customer_id, request.get_json())
    return jsonify(customer=customer, message="Customer updated.")


@bp.delete("/<int:customer_id>")
def delete_customer(customer_id):
    customers.delete_customer(customer_id)
    return jsonify(message="Customer deleted.")
