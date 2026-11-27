import sqlite3

from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import (
    BadRequest,
    RequestEntityTooLarge,
    UnsupportedMediaType,
)

import categories
import vehicles


bp = Blueprint("inventory", __name__, url_prefix="/api")


@bp.before_request
def limit_request_size():
    request.max_content_length = 64 * 1024


@bp.errorhandler(categories.CategoryValidationError)
@bp.errorhandler(vehicles.VehicleValidationError)
def invalid_inventory(error):
    return jsonify(error=str(error)), 400


@bp.errorhandler(categories.CategoryNotFoundError)
@bp.errorhandler(vehicles.VehicleNotFoundError)
def missing_inventory(error):
    return jsonify(error=str(error)), 404


@bp.errorhandler(BadRequest)
def invalid_json(error):
    return jsonify(error="Request body must contain valid JSON."), 400


@bp.errorhandler(UnsupportedMediaType)
def unsupported_content_type(error):
    return jsonify(
        error="Send inventory details as application/json."
    ), 415


@bp.errorhandler(RequestEntityTooLarge)
def oversized_request(error):
    return jsonify(
        error="Inventory details exceed the request size limit."
    ), 413


@bp.errorhandler(sqlite3.DatabaseError)
def database_error(error):
    current_app.logger.exception("Inventory database operation failed")
    return jsonify(
        error="Unable to save or load inventory records. Please try again."
    ), 500


@bp.get("/categories")
def list_categories():
    return jsonify(categories=categories.list_categories())


@bp.get("/categories/<int:category_id>")
def get_category(category_id):
    return jsonify(category=categories.get_category(category_id))


@bp.post("/categories")
def create_category():
    category = categories.create_category(request.get_json())
    response = jsonify(
        category=category,
        message="Category created.",
    )
    response.status_code = 201
    response.headers["Location"] = (
        f"/api/categories/{category['category_id']}"
    )
    return response


@bp.put("/categories/<int:category_id>")
def update_category(category_id):
    category = categories.update_category(
        category_id, request.get_json()
    )
    return jsonify(category=category, message="Category updated.")


@bp.delete("/categories/<int:category_id>")
def delete_category(category_id):
    categories.delete_category(category_id)
    return jsonify(message="Category deleted.")


@bp.get("/vehicles")
def list_vehicles():
    return jsonify(vehicles=vehicles.list_vehicles())


@bp.get("/vehicles/<int:vehicle_id>")
def get_vehicle(vehicle_id):
    return jsonify(vehicle=vehicles.get_vehicle(vehicle_id))


@bp.post("/vehicles")
def create_vehicle():
    vehicle = vehicles.create_vehicle(request.get_json())
    response = jsonify(
        vehicle=vehicle,
        message="Vehicle created.",
    )
    response.status_code = 201
    response.headers["Location"] = (
        f"/api/vehicles/{vehicle['vehicle_id']}"
    )
    return response


@bp.put("/vehicles/<int:vehicle_id>")
def update_vehicle(vehicle_id):
    vehicle = vehicles.update_vehicle(
        vehicle_id, request.get_json()
    )
    return jsonify(vehicle=vehicle, message="Vehicle updated.")


@bp.delete("/vehicles/<int:vehicle_id>")
def delete_vehicle(vehicle_id):
    vehicles.delete_vehicle(vehicle_id)
    return jsonify(message="Vehicle deleted.")


@bp.get("/vehicles/<int:vehicle_id>/availability")
def get_availability(vehicle_id):
    availability = vehicles.get_vehicle_availability(
        vehicle_id,
        request.args.get("pickup_at"),
        request.args.get("due_at"),
    )
    return jsonify(availability=availability)