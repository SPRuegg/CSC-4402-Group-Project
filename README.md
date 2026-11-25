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
python app.py
```

If PowerShell blocks activation, use the virtual environment directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

### macOS and Linux

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 in your browser. The interface requires `static/index.html` and its assets to be present on the current branch.

Press Ctrl+C to stop the server. Run `deactivate` to leave an activated virtual environment. On later runs, activate the existing environment and run `python app.py`; creating the environment is only needed once.

Starting Flask does not initialize the database schema. The default database path is `instance/car_rental.sqlite3`; set `DATABASE_PATH` to use another location.
