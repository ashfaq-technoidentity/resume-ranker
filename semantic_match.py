"""Layer 2 semantic matching: candidate chunks vs job description chunks.

A candidate is fetched by id from the resumes database; their skills and
experience are embedded as two separate chunks and compared (cosine
similarity) against separately provided JD skills and responsibilities
texts. Candidates missing parsed experience fall back to other resume
fields; a pair whose chunk is empty scores 0. Run directly for a demo:

    python semantic_match.py [--candidate-id N]
"""

import argparse

import numpy as np
from dotenv import load_dotenv

import db
from embedding_provider import EmbeddingProvider, get_embedding_provider

CANDIDATE_ID = 2

SAMPLE_JD_SKILLS = """\
Strong Python programming and software engineering fundamentals
Deep learning frameworks (TensorFlow, PyTorch, Keras)
Retrieval-Augmented Generation (RAG) and LLM application development
RESTful API development and microservices architecture
PostgreSQL database design and query optimization
Cloud deployment on AWS with Docker containerization
Monitoring and observability tooling (Prometheus, Grafana)
"""

SAMPLE_JD_RESPONSIBILITIES = """\
Design, build, and deploy machine-learning models in production
Develop LLM pipelines with retrieval augmentation and confidence scoring
Build and maintain REST APIs serving ML inference at scale
Orchestrate long-running workflows with fault tolerance on cloud infrastructure
Optimize model performance, GPU utilization, and inference costs
Author technical documentation and collaborate in Agile/Scrum teams
"""


def build_candidate_chunks(record: dict) -> tuple[str, str]:
    """Return (skills chunk, experience chunk) for one stored resume record.

    When the parser found no experience bullet points, the experience chunk
    falls back to designation, company names, and total experience.
    """
    skills = ", ".join(record.get("skills") or [])
    experience_lines = list(record.get("raw", {}).get("experience") or [])
    if not experience_lines:
        experience_lines.extend(record.get("designation") or [])
        experience_lines.extend(record.get("company_names") or [])
        total_experience = record.get("total_experience") or 0
        if total_experience > 0:
            experience_lines.append(f"{total_experience} years of total experience")
    return skills, "\n".join(experience_lines)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    vec_a = np.asarray(a, dtype=float)
    vec_b = np.asarray(b, dtype=float)
    norm = float(np.linalg.norm(vec_a) * np.linalg.norm(vec_b))
    if norm == 0.0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / norm)


def semantic_similarity(
    provider: EmbeddingProvider,
    candidate_id: int,
    jd_skills: str,
    jd_responsibilities: str,
    db_path: str = db.DEFAULT_DB_PATH,
) -> dict:
    """Fetch a candidate by id from the database and match them against a JD.

    The candidate's skills and experience chunks are compared (cosine
    similarity) with the given JD skills and responsibilities texts. Pairs
    whose chunk is empty are not sent to the provider and score 0.0; the
    average always covers both pairs.
    """
    conn = db.get_connection(db_path)
    try:
        record = db.get_resume(conn, candidate_id)
    finally:
        conn.close()
    if record is None:
        raise RuntimeError(f"candidate id {candidate_id} not found in {db_path}")

    candidate_skills, candidate_experience = build_candidate_chunks(record)
    pairs = (
        ("skills_similarity", candidate_skills, jd_skills),
        ("experience_similarity", candidate_experience, jd_responsibilities),
    )
    comparable_texts = [
        text
        for _, candidate_text, jd_text in pairs
        if candidate_text and jd_text
        for text in (candidate_text, jd_text)
    ]
    vectors = iter(provider.embed_texts(comparable_texts))

    result: dict = {
        "model": getattr(provider, "model", "unknown"),
        "candidate_name": record.get("name") or f"candidate {candidate_id}",
        "candidate_skills": candidate_skills,
        "candidate_experience": candidate_experience,
    }
    similarities: list[float] = []
    for name, candidate_text, jd_text in pairs:
        if candidate_text and jd_text:
            similarity = cosine_similarity(next(vectors), next(vectors))
        else:
            similarity = 0.0
        result[name] = similarity
        similarities.append(similarity)
    result["average_similarity"] = sum(similarities) / len(similarities)
    return result


def _preview(text: str, width: int = 100) -> str:
    return " ".join(text.split())[:width] or "(empty)"


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
    try:
        provider = get_embedding_provider()
        result = semantic_similarity(
            provider,
            args.candidate_id,
            SAMPLE_JD_SKILLS,
            SAMPLE_JD_RESPONSIBILITIES,
            db_path=args.db,
        )
    except RuntimeError as error:
        raise SystemExit(
            f"Cannot match candidate id {args.candidate_id}: {error}"
        ) from error

    print(f"Candidate: {result['candidate_name']} (id {args.candidate_id})")
    print(f"Model:     {result['model']}")
    print(f"Skills chunk:     {_preview(result['candidate_skills'])}")
    print(f"Experience chunk: {_preview(result['candidate_experience'])}")
    print(f"JD skills:          {_preview(SAMPLE_JD_SKILLS)}")
    print(f"JD responsibilities: {_preview(SAMPLE_JD_RESPONSIBILITIES)}")
    print(f"Skills similarity:     {result['skills_similarity']:.4f}")
    print(f"Experience similarity: {result['experience_similarity']:.4f}")
    print(f"Average similarity:    {result['average_similarity']:.4f}")


if __name__ == "__main__":
    main()
