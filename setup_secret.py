
import secrets
from pathlib import Path

# Generate a secure random secret key
secret_key = secrets.token_hex(32)

# Create a .env file in the project folder
env_file = Path(__file__).parent / ".env"

env_file.write_text(
    f'FLASK_SECRET_KEY={secret_key}\n',
    encoding="utf-8"
)

print("Secret key created successfully!")
print(".env file saved in your clothing store folder.")
