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
    job_id: str
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


class JobScoreRecord(BaseModel):
    """One stored ranking: how a stored resume scored against a job."""

    resume_id: int
    job_id: str
    name: str | None = None
    email: str | None = None
    file_name: str | None = None
    skills: list[str] = Field(default_factory=list)
    total_experience: float | None = None
    skills_similarity: float
    experience_similarity: float
    average_similarity: float
    model: str | None = None
    updated_at: str


class AgentSessionRecord(BaseModel):
    """One AI-assistant chat session (each owns a Docker sandbox)."""

    id: str
    title: str
    sandbox_status: str
    sandbox_container_id: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentMessageRecord(BaseModel):
    """One chat message: the user's question or the assistant's final answer."""

    id: int
    session_id: str
    run_id: str | None = None
    role: str
    content: str
    created_at: datetime


class AgentEventRecord(BaseModel):
    """One append-only agent trace event (thought, action, observation, ...)."""

    id: int
    session_id: str
    run_id: str | None = None
    seq: int
    type: str
    data: dict = Field(default_factory=dict)
    created_at: datetime


class AgentSessionDetail(BaseModel):
    """Session with its chat messages and full event trace, for replay."""

    session: AgentSessionRecord
    messages: list[AgentMessageRecord] = Field(default_factory=list)
    events: list[AgentEventRecord] = Field(default_factory=list)


class AgentChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class AgentSessionRename(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class SandboxStatus(BaseModel):
    """State of a session's Docker sandbox container."""

    container_id: str | None = None
    name: str | None = None
    image: str | None = None
    status: str | None = None
    running: bool = False
    started_at: str | None = None
    workspace_volume: str | None = None
    mem_usage: str | None = None
    cpu_percent: float | None = None


class SandboxFileEntry(BaseModel):
    """One entry of a sandbox directory listing."""

    name: str
    path: str
    size: int
    is_dir: bool
    mtime: float | None = None


class SandboxFileContent(BaseModel):
    """Contents of one sandbox file (text, size-capped)."""

    path: str
    size: int
    truncated: bool = False
    binary: bool = False
    content: str
