import argparse
import glob
import json
import os

from pydantic import ValidationError
from pydparser import ResumeParser
from pydparser import utils as parser_utils

import db
from models import ParsedResume

_TEXT_EXTRACT_EXTENSIONS = (".pdf", ".docx", ".doc")


def extract_resume_text(file_path: str) -> str | None:
    """Extract the full plain text of a resume file, or None on failure.

    Uses the same extraction functions as the parser itself, so the stored
    text matches what pydparser saw when it parsed the file.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in _TEXT_EXTRACT_EXTENSIONS:
        return None
    try:
        text = parser_utils.extract_text(file_path, ext)
    except Exception:  # noqa: BLE001 - fail-soft: text extraction must never break parsing
        return None
    return text or None


def parse_resume(file_path: str) -> dict:
    try:
        data = ResumeParser(file_path).get_extracted_data()
    except Exception as e:  # noqa: BLE001 - fail-soft: any parser failure becomes an error record
        return {"file_path": file_path, "error": str(e)}
    data["file_path"] = file_path
    data["resume_text"] = extract_resume_text(file_path)
    return data


def _to_parsed_resume(data: dict) -> ParsedResume:
    if "error" in data:
        return ParsedResume(
            file_path=data["file_path"],
            error=data["error"],
            raw=data,
        )
    try:
        return ParsedResume(
            file_path=data["file_path"],
            name=data.get("name"),
            email=data.get("email"),
            mobile_number=data.get("mobile_number"),
            skills=data.get("skills") or [],
            degree=data.get("degree") or [],
            designation=data.get("designation") or [],
            company_names=data.get("company_names") or [],
            college_name=data.get("college_name") or [],
            total_experience=data.get("total_experience"),
            no_of_pages=data.get("no_of_pages"),
            resume_text=data.get("resume_text"),
            raw=data,
        )
    except ValidationError as e:
        return ParsedResume(
            file_path=data.get("file_path", ""),
            error=str(e),
            resume_text=data.get("resume_text"),
            raw=data,
        )


def parse_file(file_path: str) -> ParsedResume:
    """Parse a single resume file; parser failures become ParsedResume error records."""
    return _to_parsed_resume(parse_resume(file_path))


def parse_resumes(folder_path: str) -> list[ParsedResume]:
    results: list[ParsedResume] = []
    for pattern in ("*.pdf", "*.docx"):
        for file_path in glob.glob(os.path.join(folder_path, pattern)):
            results.append(parse_file(file_path))
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Parse resumes in a folder to JSON and SQLite."
    )
    parser.add_argument(
        "folder_path", help="Path to the folder containing PDF/DOCX resumes"
    )
    parser.add_argument(
        "--db",
        default=db.DEFAULT_DB_PATH,
        help=f"Path to the SQLite database file (default: {db.DEFAULT_DB_PATH})",
    )
    args = parser.parse_args()

    parsed = parse_resumes(args.folder_path)
    output = [item.model_dump() for item in parsed]
    with open("parsed_resumes.json", "w") as f:
        json.dump(output, f, indent=2)

    conn = db.get_connection(args.db)
    try:
        db.save_resumes(conn, parsed)
    finally:
        conn.close()

    print(f"Parsed {len(parsed)} resume(s) and wrote parsed_resumes.json")
    print(f"Stored {len(parsed)} resume(s) in {args.db}")


if __name__ == "__main__":
    main()
