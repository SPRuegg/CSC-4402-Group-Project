from flask import Flask, redirect, url_for


def create_app():
    app = Flask(__name__)

    @app.get("/")
    def index():
        return redirect(url_for("static", filename="index.html"))

    return app


if __name__ == "__main__":
    create_app().run()
