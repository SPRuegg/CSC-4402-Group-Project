import os
from pathlib import Path

from flask import Flask, redirect, url_for

import db
from customer_routes import bp as customer_blueprint
from inventory_routes import bp as inventory_blueprint
from rental_routes import bp as rental_blueprint
from billing_routes import bp as billing_blueprint

def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE=os.environ.get(
            "DATABASE_PATH", str(Path(app.instance_path) / "car_rental.sqlite3")
        )
    )
    if test_config is not None:
        app.config.update(test_config)
    db.init_app(app)
    app.register_blueprint(customer_blueprint)
    app.register_blueprint(inventory_blueprint)
    app.register_blueprint(rental_blueprint)
    app.register_blueprint(billing_blueprint)
    @app.get("/")
    def index():
        return redirect(url_for("static", filename="index.html"))

    return app


if __name__ == "__main__":
    create_app().run()
