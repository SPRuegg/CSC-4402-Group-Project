# CSC 4402 Group Project

## Dependencies

- Python 3.10 or newer.
- On Linux, install your distribution's Python venv package if venv support is missing.

## Run the Flask application

Open a terminal in the project folder.

### Windows (PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python generate_data.py
python app.py
```

If PowerShell blocks activation, use the virtual environment directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe generate_data.py
.\.venv\Scripts\python.exe app.py
```

### macOS and Linux

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python generate_data.py
python app.py
```

Open http://127.0.0.1:5000 in your browser. The interface requires `static/index.html` and its assets to be present on the current branch.

Press Ctrl+C to stop the server. Run `deactivate` to leave an activated virtual environment. On later runs, activate the existing environment and run `python app.py`; creating the environment is only needed once.

### Sample database setup

`python generate_data.py` creates the schema and fictional sample records in `instance/car_rental.sqlite3`. Run it before starting Flask for the first time. If the database already exists, the generator preserves it and exits; continue with `python app.py` to use the existing data.

To intentionally reset the database, run:

```sh
python generate_data.py --overwrite
```

This replaces the existing database and its data.

Use `--db` to generate a database at another path:

```sh
python generate_data.py --db instance/practice.sqlite3
```

Flask must use the same path. Set `DATABASE_PATH` before running `python app.py`:

Windows (PowerShell):

```powershell
$env:DATABASE_PATH = "instance/practice.sqlite3"
python app.py
```

macOS and Linux:

```sh
DATABASE_PATH=instance/practice.sqlite3 python app.py
```

Starting Flask alone does not initialize the database schema.
