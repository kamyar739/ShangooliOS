import argparse
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from database import (
    create_artwork,
    get_artwork,
    get_artwork_folder,
    initialize_artwork_workspace,
    initialize_database,
    list_artworks,
    list_brands,
    list_collections,
    seed_data,
    update_artwork,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ShangooliOS")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("hello")
    subparsers.add_parser("init-db")
    subparsers.add_parser("seed")
    subparsers.add_parser("brands")
    subparsers.add_parser("collections")

    artwork_parser = subparsers.add_parser("artwork")
    artwork_subparsers = artwork_parser.add_subparsers(
        dest="artwork_command",
        required=True,
    )

    new_parser = artwork_subparsers.add_parser("new")
    new_parser.add_argument("--collection")
    new_parser.add_argument("--title")
    new_parser.add_argument("--working-title")
    new_parser.add_argument("--theme")

    artwork_subparsers.add_parser("list")

    show_parser = artwork_subparsers.add_parser("show")
    show_parser.add_argument("artwork_code")

    edit_parser = artwork_subparsers.add_parser("edit")
    edit_parser.add_argument("artwork_code")

    workspace_parser = artwork_subparsers.add_parser("workspace")
    workspace_parser.add_argument("artwork_code")

    return parser


def ask(value: str | None, prompt: str, default: str | None = None) -> str:
    if value is not None:
        return value.strip()

    label = prompt
    if default:
        label += f" [{default}]"
    label += ": "

    response = input(label).strip()
    if response:
        return response
    if default is not None:
        return default
    return ""


def print_artwork(row) -> None:
    print(f"{row['artwork_code']} — {row['public_title']}")
    print(f"Collection: {row['collection_name']}")
    print(f"Working title: {row['working_title'] or '-'}")
    print(f"Theme: {row['theme'] or '-'}")
    print(f"Story: {row['story'] or '-'}")
    print(f"Status: {row['status']}")
    print(f"Folder: {get_artwork_folder(row)}")


def main() -> None:
    args = build_parser().parse_args()

    try:
        if args.command == "hello":
            print("ShangooliOS is running.")

        elif args.command == "init-db":
            initialize_database()
            print("Database initialized.")

        elif args.command == "seed":
            seed_data()
            print("Brand and collections seeded.")

        elif args.command == "brands":
            rows = list_brands()
            if not rows:
                print("No brands found. Run: python app/main.py seed")
                return
            for row in rows:
                print(f"{row['code']}: {row['name']} | {row['status']}")

        elif args.command == "collections":
            rows = list_collections()
            if not rows:
                print("No collections found. Run: python app/main.py seed")
                return
            for row in rows:
                print(
                    f"{row['brand_name']} > {row['code']}: {row['name']} | "
                    f"{row['status']} | target {row['target_artwork_count']}"
                )

        elif args.command == "artwork":
            if args.artwork_command == "new":
                collection = ask(args.collection, "Collection", "CEL")
                title = ask(args.title, "Public title")
                working_title = ask(args.working_title, "Working title", "")
                theme = ask(args.theme, "Theme", "")

                result = create_artwork(
                    collection_code=collection,
                    public_title=title,
                    working_title=working_title or None,
                    theme=theme or None,
                )
                print(f"Artwork created: {result['artwork_code']}")
                print(f"Workspace created: {result['folder_path']}")

            elif args.artwork_command == "list":
                rows = list_artworks()
                if not rows:
                    print("No artworks found.")
                    return
                for row in rows:
                    print(
                        f"{row['artwork_code']}: {row['public_title']} | "
                        f"{row['status']} | {row['collection_name']}"
                    )

            elif args.artwork_command == "show":
                row = get_artwork(args.artwork_code)
                if row is None:
                    raise ValueError(f"Artwork not found: {args.artwork_code}")
                print_artwork(row)

            elif args.artwork_command == "edit":
                row = get_artwork(args.artwork_code)
                if row is None:
                    raise ValueError(f"Artwork not found: {args.artwork_code}")

                print("Press Enter to keep the current value.")
                public_title = ask(None, "Public title", row["public_title"])
                working_title = ask(None, "Working title", row["working_title"] or "")
                theme = ask(None, "Theme", row["theme"] or "")
                story = ask(None, "Story", row["story"] or "")
                status = ask(None, "Status", row["status"])

                update_artwork(
                    artwork_code=args.artwork_code,
                    public_title=public_title,
                    working_title=working_title or None,
                    theme=theme or None,
                    story=story or None,
                    status=status,
                )
                print(f"Artwork updated: {args.artwork_code.upper()}")

            elif args.artwork_command == "workspace":
                row = get_artwork(args.artwork_code)
                if row is None:
                    raise ValueError(f"Artwork not found: {args.artwork_code}")
                folder = initialize_artwork_workspace(row)
                print(f"Workspace ready: {folder}")

    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
