from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


class ParsedResume(BaseModel):
    file_path: str
    name: str | None = None
    email: str | None = None
    mobile_number: str | None = None
    skills: list[str] = Field(default_factory=list)
    degree: list[str] = Field(default_factory=list)
    designation: list[str] = Field(default_factory=list)
    company_names: list[str] = Field(default_factory=list)
    college_name: list[str] = Field(default_factory=list)
    total_experience: float | None = None
    no_of_pages: int | None = None
    resume_text: str | None = None
    raw: dict = Field(default_factory=dict)
    error: str | None = None


class JobDescription(BaseModel):
    job_id: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    posted_date: date | None = None
    job_skills: list[str] = Field(default_factory=list)
    job_responsibilities: list[str] = Field(default_factory=list)


class JobDescriptionUpdate(BaseModel):
    """Partial update: only fields present in the request body are changed."""

    description: str | None = Field(default=None, min_length=1)
    posted_date: date | None = None
    job_skills: list[str] | None = None
    job_responsibilities: list[str] | None = None


class StoredJobDescription(BaseModel):
    job_id: str
    description: str
    posted_date: date
    created_at: datetime
    updated_at: datetime
    job_skills: list[str] = Field(default_factory=list)
    job_responsibilities: list[str] = Field(default_factory=list)

    @field_validator("job_skills", "job_responsibilities", mode="before")
    @classmethod
    def _null_becomes_empty_list(cls, value: object) -> object:
        return [] if value is None else value


class KeywordMatch(BaseModel):
    keyword: str
    count: int


class ResumeSearchRequest(BaseModel):
    keywords: list[str] = Field(min_length=1, max_length=50)


class ResumeSearchResult(BaseModel):
    id: int
    name: str | None = None
    email: str | None = None
    file_name: str | None = None
    skills: list[str] = Field(default_factory=list)
    total_experience: float | None = None
    distinct_keywords: int
    total_matches: int
    matched_keywords: list[KeywordMatch] = Field(default_factory=list)


class ResumeRankResult(BaseModel):
    """Result of the rank workflow: stored resume summary + similarity scores."""

    resume_id: int
    file_name: str | None = None
    file_hash: str | None = None
    name: str | None = None
    email: str | None = None
    skills: list[str] = Field(default_factory=list)
    total_experience: float | None = None
    model: str
    candidate_skills: str
    candidate_experience: str
    skills_similarity: float
    experience_similarity: float
    average_similarity: float
