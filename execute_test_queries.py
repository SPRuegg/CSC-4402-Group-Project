import os
import sqlite3
from pathlib import Path
 
# Connect to the database
db_path = Path(__file__).parent / "instance" / "car_rental.sqlite3"
conn = sqlite3.connect(db_path) #os.environ["DATABASE_PATH"]
cursor = conn.cursor()
 
# Define parameters
params = {
    "REFERENCE_TIME": "2026-12-01 08:00:00",
    "PICKUP_DATE": "2026-12-01 08:00:00",
    "DROPOFF_DATE": "2026-12-05 17:00:00"
}

sql_path = Path(__file__).parent / "sql" / "test_queries.sql"

# Read SQL from file
with open(file=sql_path, mode="r", encoding="utf-8") as file:
    sql = file.read()
 
# Process individual SQL statements
statement = ""
query_number = 0
 
for character in sql:
    statement += character
    
 
    if character == ";" and sqlite3.complete_statement(statement):
        
        query_number += 1
            

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