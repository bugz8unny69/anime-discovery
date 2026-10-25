"""Local privileged password recovery through the API's Unix socket."""
import argparse
import getpass
import json
import socket
import sys


def main():
    parser = argparse.ArgumentParser(description="Anime Discovery local administration")
    parser.add_argument("command", nargs="?", choices=("set-password",))
    parser.add_argument("--set-password", action="store_true",
                        help="Alias for the set-password subcommand")
    parser.add_argument("--socket", default="/run/anime-discovery/admin.sock")
    parser.add_argument("--password-stdin", action="store_true", help="Read a password from standard input for automation")
    parser.add_argument("--if-unset", action="store_true", help="Initialize only; preserve an existing password")
    args = parser.parse_args()
    if bool(args.command) == args.set_password:
        parser.error("Specify exactly one of set-password or --set-password")
    command = args.command or "set-password"
    if args.password_stdin:
        password = sys.stdin.buffer.read(1026).decode('utf-8').removesuffix('\n')
    else:
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
        request = {"command": command, "password": password}
        if args.if_unset:request["if_unset"] = True
        payload = json.dumps(request).encode()
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
    if result.get("unchanged"):
        print("Existing administrator password preserved.")
        return
    print("Administrator password updated; existing dashboard sessions are invalidated.")


if __name__ == "__main__":
    main()
