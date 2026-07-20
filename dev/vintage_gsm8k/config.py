"""Configuration and artifact paths for the Vintage GSM8K pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "vintage-gsm8k"

DATASET_ID = "openai/gsm8k"
DATASET_SUBSET = "main"
EXPECTED_COUNTS = {"train": 7473, "test": 1319}
CUTOFF_YEAR = 1930

NORMALIZATION_VERSION = "gsm8k-strip-calculator-v1"
JUDGE_PROMPT_VERSION = "vintage-gsm8k-judge-v1"
REWRITE_PROMPT_VERSION = "vintage-gsm8k-rewrite-v1"
SOLVER_PROMPT_VERSION = "vintage-gsm8k-solver-v1"

CHAT_ENDPOINT = "https://opencode.ai/zen/v1/chat/completions"
RESPONSES_ENDPOINT = "https://opencode.ai/zen/v1/responses"
JUDGE_MODEL = "deepseek-v4-flash-free"
REWRITE_MODEL = "mimo-v2.5-free"
SOLVER_MODEL = "gpt-5.6-sol"

TOOL_TOKEN_FRAGMENTS = (
    "<|python_start|>",
    "<|python_end|>",
    "<|python_output_start|>",
    "<|python_output_end|>",
    "<|tool",
)


@dataclass(frozen=True)
class PipelinePaths:
    """All pipeline outputs live below one relocatable artifact root."""

    root: Path = DEFAULT_ARTIFACT_ROOT

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root).resolve())

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.json"

    @property
    def source_dir(self) -> Path:
        return self.root / "source"

    def source(self, split: str) -> Path:
        return self.source_dir / f"{split}.jsonl"

    @property
    def audit_dir(self) -> Path:
        return self.root / "audit"

    def judge(self, split: str) -> Path:
        return self.audit_dir / f"judge-{split}.jsonl"

    def verify(self, split: str) -> Path:
        return self.audit_dir / f"verify-{split}.jsonl"

    @property
    def calls(self) -> Path:
        return self.audit_dir / "calls.jsonl"

    @property
    def review_dir(self) -> Path:
        return self.root / "review"

    @property
    def review_markdown(self) -> Path:
        return self.review_dir / "judge.md"

    @property
    def decisions(self) -> Path:
        return self.review_dir / "decisions.jsonl"

    @property
    def staging_dir(self) -> Path:
        return self.root / "staging"

    def rewrites(self, split: str) -> Path:
        return self.staging_dir / f"rewrite-{split}.jsonl"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    def packaged(self, split: str) -> Path:
        return self.data_dir / f"{split}.jsonl"
