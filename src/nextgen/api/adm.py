"""Local privileged password recovery through the API's Unix socket."""
import argparse
import getpass
import json
import socket


def main():
    parser = argparse.ArgumentParser(description="NextGen local administrator recovery")
    parser.add_argument("command", choices=("set-password",))
    parser.add_argument("--socket", default="/run/anime-discovery/admin.sock")
    args = parser.parse_args()
    password = getpass.getpass("New administrator password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        parser.error("Passwords do not match")
    from src.nextgen.api.passwords import validate_password
    try:
        validate_password(password)
    except ValueError:
        parser.error("Password must be 12–256 characters with no control characters")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(15)
        conn.connect(args.socket)
        payload = json.dumps({"command": args.command, "password": password}).encode()
        conn.sendall(payload + bytes([10]))
        response = b""
        while not response.endswith(bytes([10])) and len(response) < 2048:
            part = conn.recv(2048)
            if not part:
                break
            response += part
    try:
        result = json.loads(response)
    except (ValueError, UnicodeError):
        parser.error("Invalid admin socket response")
    if result.get("ok") is not True:
        parser.error("Password change failed")
    print("Administrator password updated; existing dashboard sessions are invalidated.")


if __name__ == "__main__":
    main()
