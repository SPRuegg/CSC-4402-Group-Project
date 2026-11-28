import os
import sqlite3
from pathlib import Path
import argparse

"""
Reads and Executes "test_queries.sql" in sql folder

USAGE: 
    Read and perform steps in README.md
     Note: It is recommended to use a seed when generating the file to get matching results with example file.
     --seed 7
    python execute_test_queries.py


OPTIONAL PARAMETERS:
    --db : ./instance/FILE_NAME with FILE_NAME replaced with the database file, will use that as the instance. DEFAULT=instance/car_rental.sqlite3
    --reference_time : Reference time for overdue cars and payments. DEFAULT=2026-12-01 08:00:00
    --pickup_date : Request for a rental pickup date. DEFAULT=2026-12-01 08:00:00
    --dropoff_date : Requested rental dropoff date. DEFAULT=2026-12-05 17:00:00

    
This file only queries, it will not modify existing database files.
This is set to only work with test_queries.sql in this stage.


RECOMMENDATIONS:
    Output the contents this file produces into another file for redability purposes, 
    as ALL sql queries are executed at once.
    Example: python ./CSC-4402-Group-Project/execute_test_queries.py --db ./instance/practice.sqlite3 > something.txt
"""



#Arguments for program (optional)
parser = argparse.ArgumentParser(description="Execute the SQL test queries against a car rental database.")
parser.add_argument("--db", default="instance/car_rental.sqlite3", help="Database file path (default: instance/car_rental.sqlite3)")
parser.add_argument("--reference_time", default="2026-12-01 08:00:00", help="Reference time for query calculations")
parser.add_argument("--pickup_date", default="2026-12-01 08:00:00", help="Requested rental pickup date")
parser.add_argument("--dropoff_date", default="2026-12-05 17:00:00", help="Requested rental dropoff date")
args = parser.parse_args()

 
# Connect to the database

 
# Define SQL parameters
params = {
    "REFERENCE_TIME": args.reference_time,
    "PICKUP_DATE": args.pickup_date,
    "DROPOFF_DATE": args.dropoff_date
}

#Construct baseline file path intentions
base_path = Path(__file__).parent
db_path = Path(args.db)

#Check for specific path location
if not db_path.is_absolute():
    db_path = base_path / db_path

#Check if database file exist
if not db_path.exists():
    raise FileNotFoundError(f"Database not found: {db_path}")

#connect sqlite3 to database file
conn = sqlite3.connect(db_path) #os.environ["DATABASE_PATH"]
cursor = conn.cursor()

#locate sql file
sql_path = Path(__file__).parent / "sql" / "test_queries.sql"

# Read SQL from file
with open(file=sql_path, mode="r", encoding="utf-8") as file:
    sql = file.read()
 
# Process individual SQL statements
statement = ""
query_number = 0
 
for character in sql:
    statement += character
    
    #Check for end-of-line sql line
    if character == ";" and sqlite3.complete_statement(statement):
        
        query_number += 1

        #Print query instruction being executed
        print(f"\nQUERY {query_number}")
        print("=" * 100)
        #print(statement.strip())
 
        try:
            # Execute SQL with parameters
            cursor.execute(statement, params)
 
            if cursor.description is not None:
 
                # Retrieve results
                rows = cursor.fetchall()
 
                # Display column names
                print(" | ".join(
                    col[0] for col in cursor.description
                ))
                print("-" * 100)
 
                # Display results
                for row in rows:
                    print(" | ".join(str(value) for value in row))
 
                print(f"\nTotal rows returned: {len(rows)}")
 
            else:
                print(f"Rows affected: {cursor.rowcount}")
 
        except sqlite3.Error as error:
            print(f"SQL Error: {error}")
 
        # Reset for next query
        statement = ""
 
# Close connection
conn.close()