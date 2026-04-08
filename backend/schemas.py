from pydantic import BaseModel, Field


class DiffRequest(BaseModel):
    text_a: str = Field(..., min_length=1, max_length=5000)
    text_b: str = Field(..., min_length=1, max_length=5000)


class JobStartResponse(BaseModel):
    job_id: str
    request_id: str
    status: str

