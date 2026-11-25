"""Create the local .env file with random database passwords (for docker compose).

    python tools/make_env.py            # creates .env, does nothing if it already exists
    python tools/make_env.py --force    # replaces it (the database volume must be deleted too:
                                        #   docker compose down -v)

The .env file is in .gitignore: the passwords exist only on this machine.
"""
import argparse
import pathlib
import secrets
import string

ROOT = pathlib.Path(__file__).resolve().parent.parent
ALPHABET = string.ascii_letters + string.digits  # letters and digits only: they go into URLs


def new_password():
    # The fixed ending guarantees upper case, lower case and a digit, which SQL Server requires.
    return "".join(secrets.choice(ALPHABET) for _ in range(20)) + "Aa1"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="replace an existing .env")
    parser.add_argument("--root", type=pathlib.Path, default=ROOT, help="repo root (for tests)")
    args = parser.parse_args()

    target = args.root / ".env"
    if target.exists() and not args.force:
        print(f"{target} already exists, nothing changed (use --force to replace it)")
        return
    lines = [f"{name}={new_password()}" for name in
             ("SA_PASSWORD", "VEHICLES_DB_PASSWORD", "RESERVATIONS_DB_PASSWORD")]
    target.write_text("\n".join(lines) + "\n")
    print(f"created {target}")


if __name__ == "__main__":
    main()