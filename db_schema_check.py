import os
import pyodbc
from dotenv import load_dotenv

load_dotenv()

server = os.getenv('DB_SERVER')
database = os.getenv('DB_DATABASE')
username = os.getenv('DB_USERNAME')
password = os.getenv('DB_PASSWORD')
driver = os.getenv('DB_DRIVER', '{ODBC Driver 17 for SQL Server}')
trusted = str(os.getenv('DB_TRUSTED_CONNECTION')).lower() in ['yes', 'true', '1']

if trusted:
    conn_str = f"DRIVER={driver};SERVER={server};DATABASE={database};Trusted_Connection=yes;"
else:
    conn_str = f"DRIVER={driver};SERVER={server};DATABASE={database};UID={username};PWD={password};"

try:
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()

    print("--- Összes tábla a rendszerben (Schema.TableName) ---")
    cursor.execute("""
        SELECT TABLE_SCHEMA, TABLE_NAME 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_TYPE = 'BASE TABLE' 
        ORDER BY TABLE_SCHEMA, TABLE_NAME
    """)
    for row in cursor:
        print(f"{row[0]}.{row[1]}")

    print("\n--- 'dbo.patikak' tábla oszlopai ---")
    cursor.execute("""
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'patikak'
    """)
    for row in cursor:
        print(f" - {row[0]} ({row[1]} {row[2] if row[2] else ''})")

    print("\n--- 'dbo.Pharmacies' tábla oszlopai ---")
    cursor.execute("""
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'Pharmacies'
    """)
    for row in cursor:
        print(f" - {row[0]} ({row[1]} {row[2] if row[2] else ''})")

    print("\n--- Minta adat a 'dbo.patikak'-ból (Top 2 Minta) ---")
    cursor.execute("SELECT TOP 2 * FROM dbo.patikak")
    columns = [column[0] for column in cursor.description]
    print("Oszlopok:", columns)
    for row in cursor.fetchall():
        print(list(row))
        
    print("\n--- Minta adat a 'dbo.Pharmacies'-ből (Top 2 Minta) ---")
    cursor.execute("SELECT TOP 2 * FROM dbo.Pharmacies")
    columns = [column[0] for column in cursor.description]
    print("Oszlopok:", columns)
    for row in cursor.fetchall():
        print(list(row))

except Exception as e:
    print(f"Hiba történt: {e}")
