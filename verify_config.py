import os
from dotenv import load_dotenv

# Load .env file
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

print("--- Configuration Verification ---")
client_id = os.environ.get('GOOGLE_OAUTH_CLIENT_ID')
client_secret = os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET')

if client_id:
    print(f"[OK] GOOGLE_OAUTH_CLIENT_ID found: {client_id[:10]}...{client_id[-5:]}")
else:
    print("[FAIL] GOOGLE_OAUTH_CLIENT_ID NOT found!")

if client_secret:
    print(f"[OK] GOOGLE_OAUTH_CLIENT_SECRET found: {client_secret[:5]}...")
else:
    print("[FAIL] GOOGLE_OAUTH_CLIENT_SECRET NOT found!")

print(f"SERVER_NAME: {os.environ.get('SERVER_NAME')}")
print("--------------------------------")
