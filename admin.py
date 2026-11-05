```python
from getpass import getpass
from werkzeug.security import generate_password_hash
from database import get_connection


# ==========================================
# CREATE OFFGRID ADMIN ACCOUNT
# ==========================================

name = input("Enter admin name: ").strip()
email = input("Enter admin email: ").strip().lower()

if not name or not email:
    raise SystemExit("Name and email are required.")

if "@" not in email:
    raise SystemExit("Enter a valid email address.")

password = getpass("Create admin password: ")
confirm_password = getpass("Confirm admin password: ")

if len(password) < 12:
    raise SystemExit("Password must be at least 12 characters.")

if password != confirm_password:
    raise SystemExit("Passwords do not match.")


connection = get_connection()
cursor = connection.cursor()

try:
    # Check whether email already exists
    cursor.execute(
        "SELECT user_id FROM users WHERE email = %s",
        (email,)
    )

    existing_user = cursor.fetchone()

    if existing_user:
        raise SystemExit("An account with this email already exists.")

    password_hash = generate_password_hash(password)

    cursor.execute("""
        INSERT INTO users
        (full_name, email, password_hash, role)
        VALUES (%s, %s, %s, 'admin')
    """, (name, email, password_hash))

    connection.commit()

    print("\nAdmin account created successfully!")
    print("You can now log in to OFFGRID Admin.")

except Exception:
    connection.rollback()
    raise

finally:
    cursor.close()
    connection.close()
```