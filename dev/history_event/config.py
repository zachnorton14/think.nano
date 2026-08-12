"""Constants and relocatable paths for the HISTORY-EVENT pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "history-event"
DEFAULT_DATASET_REPO = "jbduran/history-event-reconstruction"

PARSER_VERSION = "history-event-wikitext-v1"
NORMALIZATION_VERSION = "history-event-visible-text-v1"
FOUR_DIGIT_FILTER_VERSION = "history-event-four-digit-v1"
BPB_SCORER_VERSION = "history-event-target-bpb-v1"
GOLD_ANSWER_PROMPT_VERSION = "history-event-deepseek-answer-v1"
GOLD_JUDGE_PROMPT_VERSION = "history-event-deepseek-judge-v1"

OPENCODE_MODEL = "deepseek-v4-flash"
OPENCODE_ENDPOINT = "https://opencode.ai/zen/go/v1/chat/completions"
CANONICAL_MODEL_FAMILIES = {
    "deepseek-v4-flash": "deepseek-v4-flash",
    "deepseek-v4-flash-free": "deepseek-v4-flash",
}

PAPER_DECADES = list(range(1700, 2030, 10))
PAPER_DECADE_COUNTS = [
    23, 19, 20, 15, 19, 15, 23, 25, 27, 42, 55,
    38, 41, 50, 44, 38, 54, 49, 46, 64, 79, 116,
    94, 87, 105, 97, 116, 134, 124, 162, 162, 198, 163,
]
PAPER_EVENT_COUNT = 2344
PAPER_RECALL_CANDIDATE_COUNT = 2148
PAPER_GOLD_COUNT = 1726

MEDIAWIKI_API = "https://en.wikipedia.org/w/api.php"
SOURCE_PAGES = (
    {
        "century": 18,
        "title": "Timeline of the 18th century",
        "revision": 1349201361,
    },
    {
        "century": 19,
        "title": "Timeline of the 19th century",
        "revision": 1352921828,
    },
    {
        "century": 20,
        "title": "Timeline of the 20th century",
        "revision": 1351931696,
    },
    {
        "century": 21,
        "title": "Timeline of the 21st century",
        "revision": 1356589916,
    },
)

BPB_PREFIX = "What do you think about the following event:"
RECALL_TEMPLATE = (
    "Do you know about the following event: {event_description}? "
    "If so, explain what this event was and in what year did it take place?"
)


@dataclass(frozen=True)
class PipelinePaths:
    root: Path = DEFAULT_ARTIFACT_ROOT

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root).resolve())

    @property
    def source_dir(self) -> Path:
        return self.root / "source"

    @property
    def raw_dir(self) -> Path:
        return self.source_dir / "raw"

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.json"

    @property
    def events(self) -> Path:
        return self.source_dir / "events.jsonl"

    @property
    def recall_candidates(self) -> Path:
        return self.source_dir / "recall-candidates.jsonl"

    @property
    def four_digit_rejections(self) -> Path:
        return self.source_dir / "four-digit-rejections.jsonl"

    @property
    def discrepancy_report(self) -> Path:
        return self.source_dir / "discrepancy.json"

    @property
    def audit_dir(self) -> Path:
        return self.root / "audit"

    @property
    def answer_audit(self) -> Path:
        return self.audit_dir / "gold-answers.jsonl"

    @property
    def judge_audit(self) -> Path:
        return self.audit_dir / "gold-judgments.jsonl"

    @property
    def call_log(self) -> Path:
        return self.audit_dir / "calls.jsonl"

    @property
    def gold_rows(self) -> Path:
        return self.audit_dir / "recall-deepseek-v1.jsonl"

    @property
    def gold_report_json(self) -> Path:
        return self.audit_dir / "gold-report.json"

    @property
    def gold_report_markdown(self) -> Path:
        return self.root / "review" / "gold.md"

    @property
    def probe(self) -> Path:
        return self.audit_dir / "paid-route-probe.json"

    @property
    def package_dir(self) -> Path:
        return self.root / "package"

    @property
    def package_manifest(self) -> Path:
        return self.package_dir / "manifest.json"

    @property
    def results_dir(self) -> Path:
        return self.root / "results"


def revision_url(title: str, revision: int) -> str:
    slug = title.replace(" ", "_")
    return f"https://en.wikipedia.org/w/index.php?title={slug}&oldid={revision}"


def canonical_model_family(model: str) -> str:
    return CANONICAL_MODEL_FAMILIES.get(model, model)
