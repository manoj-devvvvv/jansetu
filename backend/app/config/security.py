import hashlib
import bcrypt
from .settings import settings

def hash_mobile(phone: str) -> str:
    """Hashes a mobile number using SHA-256 and a pepper."""
    to_hash = f"{phone}{settings.MOBILE_HASH_PEPPER}".encode('utf-8')
    return hashlib.sha256(to_hash).hexdigest()

def hash_worker_pin(pin: str) -> str:
    """Hashes a short numeric PIN using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pin.encode('utf-8'), salt).decode('utf-8')

def verify_worker_pin(pin: str, hashed_pin: str) -> bool:
    """Verifies a PIN against a bcrypt hash."""
    return bcrypt.checkpw(pin.encode('utf-8'), hashed_pin.encode('utf-8'))
