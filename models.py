from datetime import date, datetime

from pydantic import BaseModel, Field


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
    raw: dict = Field(default_factory=dict)
    error: str | None = None


class JobDescription(BaseModel):
    job_id: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    posted_date: date | None = None


class StoredJobDescription(BaseModel):
    job_id: str
    description: str
    posted_date: date
    created_at: datetime
    updated_at: datetime
