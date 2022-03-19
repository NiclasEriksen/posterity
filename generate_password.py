import sys
from werkzeug.security import generate_password_hash


if len(sys.argv) == 2:
    pwd = sys.argv[1]
    print(generate_password_hash(pwd))
else:
    print("Usage: generate_password.py [password_to_hash]")
