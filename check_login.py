
import mysql.connector
from getpass import getpass
from pathlib import Path
from dotenv import dotenv_values
import os

# Check the .env configuration
env_path = Path(__file__).resolve().parent / ".env"
settings = dotenv_values(env_path)

print("=== CIVICFIX DATABASE DIAGNOSTIC ===")
print("ENV file found:", env_path.exists())
print("Configured user:", settings.get("MYSQL_USER"))
print("Configured host:", settings.get("MYSQL_HOST"))
print("Configured port:", settings.get("MYSQL_PORT"))
print("Password in ENV:", bool(settings.get("MYSQL_PASSWORD")))
print("System password override:", "MYSQL_PASSWORD" in os.environ)

# Test login directly without using .env
password = getpass("\nEnter your civicfix_app MySQL password: ")

try:
    connection = mysql.connector.connect(
        host="localhost",
        port=3306,
        user="civicfix_app",
        password=password,
        database="civicfix_db"
    )

    print("\nDIRECT LOGIN SUCCESSFUL!")
    print("ENV password matches:", settings.get("MYSQL_PASSWORD") == password)

    connection.close()

except mysql.connector.Error as error:
    print("\nDIRECT LOGIN FAILED!")
    print("Error code:", error.errno)
    print("Error message:", error)
