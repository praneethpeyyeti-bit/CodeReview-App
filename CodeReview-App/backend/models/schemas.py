from pydantic import BaseModel, field_validator
from typing import Literal

Severity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
FindingStatus = Literal["Open", "Accepted", "Rejected", "Fixed"]
FindingCategory = Literal[
    "Naming",
    "Design Best Practices",
    "UI Automation",
    "Performance",
    "Reliability",
    "Security",
    "General",
]


class ActivitySummary(BaseModel):
    display_name: str
    type_name: str
    is_inside_try_catch: bool
    is_inside_retry_scope: bool
    depth: int
    child_count: int = 0
    properties: dict[str, str] = {}
    is_inside_container: bool = False
    is_structural_wrapper: bool = False


class VariableSummary(BaseModel):
    name: str
    type: str
    scope: str


class ArgumentSummary(BaseModel):
    name: str
    direction: Literal["In", "Out", "InOut"]
    type: str
    has_default: bool = False


class CatchBlockSummary(BaseModel):
    exception_type: str = "Exception"
    activity_count: int = 0
    has_log_message: bool = False
    has_rethrow: bool = False


class ReviewContext(BaseModel):
    file_name: str
    zip_entry_path: str
    workflow_name: str
    activities: list[ActivitySummary]
    variables: list[VariableSummary]
    arguments: list[ArgumentSummary]
    has_global_exception_handler: bool
    has_start_log: bool
    has_end_log: bool
    imported_namespaces: list[str]
    catch_blocks: list[CatchBlockSummary] = []
    variable_usages: list[str] = []
    argument_usages: list[str] = []
    project_dependencies: dict[str, str] = {}


class Finding(BaseModel):
    id: str = ""
    file_name: str
    zip_entry_path: str
    workflow_name: str
    severity: Severity
    category: str
    rule_id: str
    rule_name: str
    activity_path: str = ""
    description: str
    recommendation: str
    auto_fixable: bool
    status: FindingStatus = "Open"
    reviewer_notes: str = ""

    @field_validator("activity_path", "zip_entry_path", "description", "recommendation", "rule_id", "rule_name", mode="before")
    @classmethod
    def none_to_empty(cls, v):
        return v if v is not None else ""


class ReviewResponse(BaseModel):
    project_name: str
    upload_mode: Literal["individual", "zip"]
    zip_file_name: str | None
    reviewed_at: str
    total_files: int
    skipped_files: list[str]
    model_id: str
    findings: list[Finding]
