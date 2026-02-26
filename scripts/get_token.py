import sys
import os
sys.path.append(os.getcwd())

from app.core.supabase import supabase
import getpass

def get_token():
    email = input("Email: ")
    password = getpass.getpass("Password: ")

    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        print("\n--- Access Token (Copy this) ---")
        print(res.session.access_token)
        print("\n--------------------------------")
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    print("Login to get Supabase JWT")
    get_token()
