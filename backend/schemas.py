from pydantic import BaseModel, Field, model_validator


class DiffRequest(BaseModel):
    text_a: str | None = Field(default=None, min_length=1, max_length=5000)
    text_b: str | None = Field(default=None, min_length=1, max_length=5000)
    audio_path_a: str | None = None
    audio_path_b: str | None = None
    video_path_a: str | None = None
    video_path_b: str | None = None

    @model_validator(mode="after")
    def _exactly_one_modality(self):
        pairs = {
            "text": (self.text_a, self.text_b),
            "audio": (self.audio_path_a, self.audio_path_b),
            "video": (self.video_path_a, self.video_path_b),
        }
        complete_pairs = [name for name, (a, b) in pairs.items() if a is not None and b is not None]
        if len(complete_pairs) != 1:
            raise ValueError(
                "DiffRequest must specify exactly one modality pair: "
                "(text_a + text_b) OR (audio_path_a + audio_path_b) OR (video_path_a + video_path_b). "
                f"Got complete pairs: {complete_pairs or 'none'}."
            )
        for name, (a, b) in pairs.items():
            if (a is None) ^ (b is None):
                raise ValueError(f"DiffRequest has incomplete {name} pair.")
        return self

    def modality(self) -> str:
        if self.text_a is not None and self.text_b is not None:
            return "text"
        if self.audio_path_a is not None and self.audio_path_b is not None:
            return "audio"
        return "video"


class JobStartResponse(BaseModel):
    job_id: str
    request_id: str
    status: str


class ReportPair(BaseModel):
    text_a: str = Field(..., min_length=1, max_length=5000)
    text_b: str = Field(..., min_length=1, max_length=5000)
    label: str = Field(..., min_length=1, max_length=200)


class ReportRequest(BaseModel):
    pairs: list[ReportPair] = Field(..., min_length=1, max_length=20)

