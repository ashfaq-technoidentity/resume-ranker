from pathlib import Path

from models import ParsedResume
from parse import parse_resume, parse_resumes

SAMPLES_DIR = Path(__file__).parent.parent / "sample_resumes"
GOOD_RESUME = SAMPLES_DIR / "omkar_pathak.docx"
BAD_RESUME = SAMPLES_DIR / "corrupted_resume.docx"


def test_parse_resume_success():
    result = parse_resume(str(GOOD_RESUME))
    assert "error" not in result
    assert result["file_path"] == str(GOOD_RESUME)
    assert result["name"] is not None
    assert "Omkar Pathak" in result["name"]
    assert result["email"] == "omkarpathak27@gmail.com"
    assert isinstance(result["skills"], list)
    assert "Python" in result["skills"]


def test_parse_resume_error():
    result = parse_resume(str(BAD_RESUME))
    assert "error" in result
    assert result["file_path"] == str(BAD_RESUME)


def test_parse_resumes_batch():
    results = parse_resumes(str(SAMPLES_DIR))
    expected_count = len(list(SAMPLES_DIR.glob("*.pdf"))) + len(
        list(SAMPLES_DIR.glob("*.docx"))
    )
    assert len(results) == expected_count
    assert all(isinstance(r, ParsedResume) for r in results)

    good = next(r for r in results if r.file_path == str(GOOD_RESUME))
    bad = next(r for r in results if r.file_path == str(BAD_RESUME))

    assert good.name is not None and "Omkar Pathak" in good.name
    assert good.email == "omkarpathak27@gmail.com"
    assert "Python" in good.skills
    assert bad.error is not None
