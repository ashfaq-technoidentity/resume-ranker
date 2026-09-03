"""Layer 2 semantic matching: candidate chunks vs job description chunks.

Candidate skills and experience are embedded as two separate chunks and
compared (cosine similarity) against a job description's skills and
responsibilities/experience chunks. Run directly for a demo on candidate 1:

    python semantic_match.py
"""

import argparse
import re

import numpy as np
from dotenv import load_dotenv

import db
from embedding_provider import EmbeddingProvider, get_embedding_provider

CANDIDATE_ID = 1

SAMPLE_JD = """\
AI/ML Engineer

We are looking for an AI/ML Engineer to design and ship production
machine-learning services for intelligent document processing.

Required Skills:
- Strong Python programming and software engineering fundamentals
- Deep learning frameworks (TensorFlow, PyTorch, Keras)
- Retrieval-Augmented Generation (RAG) and LLM application development
- RESTful API development and microservices architecture
- PostgreSQL database design and query optimization
- Cloud deployment on AWS with Docker containerization
- Monitoring and observability tooling (Prometheus, Grafana)

Responsibilities and Experience:
- Design, build, and deploy machine-learning models in production
- Develop LLM pipelines with retrieval augmentation and confidence scoring
- Build and maintain REST APIs serving ML inference at scale
- Orchestrate long-running workflows with fault tolerance on cloud infrastructure
- Optimize model performance, GPU utilization, and inference costs
- Author technical documentation and collaborate in Agile/Scrum teams
"""

_SKILLS_HEADER = re.compile(r"skill|requirement|qualification|technolog", re.IGNORECASE)
_RESPONSIBILITIES_HEADER = re.compile(r"responsibilit|dut|experience", re.IGNORECASE)


def build_candidate_chunks(record: dict) -> tuple[str, str]:
    """Return (skills chunk, experience chunk) for one stored resume record."""
    skills = ", ".join(record.get("skills") or [])
    experience = "\n".join(record.get("raw", {}).get("experience") or [])
    return skills, experience


def split_jd(description: str) -> tuple[str, str]:
    """Split a job description into (skills text, responsibilities text).

    Section headers are matched heuristically; lines before the first
    recognized header are treated as the intro and ignored.
    """
    skills_lines: list[str] = []
    responsibilities_lines: list[str] = []
    target = None
    for line in description.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        is_bullet = stripped.startswith(("-", "•"))
        is_header = not is_bullet and len(stripped) < 80
        if is_header and _SKILLS_HEADER.search(stripped):
            target = skills_lines
        elif is_header and _RESPONSIBILITIES_HEADER.search(stripped):
            target = responsibilities_lines
        elif target is not None:
            target.append(stripped.lstrip("-•").strip() or stripped)
    return "\n".join(skills_lines), "\n".join(responsibilities_lines)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    vec_a = np.asarray(a, dtype=float)
    vec_b = np.asarray(b, dtype=float)
    norm = float(np.linalg.norm(vec_a) * np.linalg.norm(vec_b))
    if norm == 0.0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / norm)


def semantic_similarity(
    provider: EmbeddingProvider,
    candidate_chunks: tuple[str, str],
    jd_chunks: tuple[str, str],
) -> dict:
    """Embed both candidates' and JD's chunks and compare them pairwise.

    Returns per-chunk cosine similarities plus their average.
    """
    candidate_skills, candidate_experience = candidate_chunks
    jd_skills, jd_responsibilities = jd_chunks
    texts = [candidate_skills, candidate_experience, jd_skills, jd_responsibilities]
    embeddings = provider.embed_texts(texts)
    skills_similarity = cosine_similarity(embeddings[0], embeddings[2])
    experience_similarity = cosine_similarity(embeddings[1], embeddings[3])
    return {
        "skills_similarity": skills_similarity,
        "experience_similarity": experience_similarity,
        "average_similarity": (skills_similarity + experience_similarity) / 2.0,
        "model": getattr(provider, "model", "unknown"),
    }


def _preview(text: str, width: int = 100) -> str:
    return " ".join(text.split())[:width]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Semantic skill matching between a stored resume and a sample JD."
    )
    parser.add_argument(
        "--candidate-id",
        type=int,
        default=CANDIDATE_ID,
        help=f"Resume id to match (default: {CANDIDATE_ID})",
    )
    parser.add_argument(
        "--db",
        default=db.DEFAULT_DB_PATH,
        help=f"Path to the SQLite database file (default: {db.DEFAULT_DB_PATH})",
    )
    args = parser.parse_args()

    load_dotenv()
    provider = get_embedding_provider()

    conn = db.get_connection(args.db)
    try:
        record = db.get_resume(conn, args.candidate_id)
    finally:
        conn.close()
    if record is None:
        raise SystemExit(f"Candidate id {args.candidate_id} not found in {args.db}")

    candidate_chunks = build_candidate_chunks(record)
    jd_chunks = split_jd(SAMPLE_JD)
    result = semantic_similarity(provider, candidate_chunks, jd_chunks)

    name = record.get("name") or f"candidate {args.candidate_id}"
    print(f"Candidate: {name} (id {args.candidate_id})")
    print(f"Model:     {result['model']}")
    print(f"Skills chunk:     {_preview(candidate_chunks[0])}")
    print(f"Experience chunk: {_preview(candidate_chunks[1])}")
    print(f"JD skills chunk:     {_preview(jd_chunks[0])}")
    print(f"JD experience chunk: {_preview(jd_chunks[1])}")
    print(f"Skills similarity:     {result['skills_similarity']:.4f}")
    print(f"Experience similarity: {result['experience_similarity']:.4f}")
    print(f"Average similarity:    {result['average_similarity']:.4f}")


if __name__ == "__main__":
    main()
