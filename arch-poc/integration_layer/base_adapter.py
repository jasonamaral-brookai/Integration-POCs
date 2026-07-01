"""
base_adapter.py — Abstract base class for all Brook EHR adapters.

Python mirror of the Java EhrAdapter interface defined in:
  spec/adapter-contract.md

Tier model:
  MUST    — abstract methods; subclasses that skip them raise TypeError at import
  SHOULD  — concrete methods that raise UnsupportedCapabilityError by default
  MAY     — concrete methods that raise UnsupportedCapabilityError by default

All adapters must call get_capabilities() to declare which SHOULD/MAY
methods they override. The platform uses this to route operations and
detect capability gaps before attempting calls.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, TypeVar

T = TypeVar("T")


# ──────────────────────────────────────────────────────────────────────────────
# Shared data types
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class AuthToken:
    access_token: str
    token_type: str = "Bearer"
    expires_in: Optional[int] = None


@dataclass
class AdapterContext:
    practice_id: str
    patient_id: str
    ehr_name: str
    auth_token: Optional[AuthToken] = None


@dataclass
class PatientDemographics:
    first_name: str
    last_name: str
    date_of_birth: str  # ISO format YYYY-MM-DD
    mrn: Optional[str] = None
    zip_code: Optional[str] = None


@dataclass
class PatientMatchResult:
    matched: bool
    ehr_patient_id: Optional[str] = None
    confidence_score: Optional[float] = None


@dataclass
class HealthCheckResult:
    healthy: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None


@dataclass
class ClinicalSnapshot:
    raw_payload: str            # CCDA XML or FHIR bundle JSON
    payload_type: str           # "CCDA" | "FHIR_BUNDLE"
    patient_id: str
    practice_id: str
    idempotency_key: str


@dataclass
class ClinicalDocument:
    content: bytes
    document_type_id: str       # From mapping config — not hardcoded
    document_subclass: str
    patient_id: str
    description: Optional[str] = None


@dataclass
class DocumentUploadResult:
    success: bool
    ehr_document_id: Optional[str] = None
    idempotency_key: Optional[str] = None


@dataclass
class BulkExportJob:
    job_id: str
    status_url: str


@dataclass
class BulkExportStatus:
    complete: bool
    manifest_url: Optional[str] = None
    error: Optional[str] = None


@dataclass
class NdjsonChunk:
    resource_type: str
    content: str                # Raw NDJSON text


@dataclass
class Order:
    order_type: str
    cpt_code: str
    patient_id: str
    ordering_provider_id: str


@dataclass
class OrderResult:
    success: bool
    ehr_order_id: Optional[str] = None


@dataclass
class OrderStatus:
    order_id: str
    status: str                 # "pending" | "signed" | "completed" | "cancelled"


@dataclass
class ClinicalNote:
    note_text: str
    note_type: str
    patient_id: str
    authored_by: Optional[str] = None


@dataclass
class NoteResult:
    success: bool
    ehr_note_id: Optional[str] = None


@dataclass
class Charge:
    cpt_code: str
    modifier: Optional[str]
    units: int
    encounter_date: str
    provider_id: str


@dataclass
class ChargeResult:
    success: bool
    ehr_charge_id: Optional[str] = None


@dataclass
class SubscriptionResult:
    subscription_id: str
    topic: str
    callback_url: str


@dataclass
class EhrErrorResponse:
    http_status: int
    body: str
    ehr_name: str


class BrookEhrErrorCode(Enum):
    RATE_LIMITED = "RATE_LIMITED"
    NOT_FOUND = "NOT_FOUND"
    PATIENT_NOT_FOUND = "PATIENT_NOT_FOUND"
    AUTH_FAILED = "AUTH_FAILED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    TRANSIENT = "TRANSIENT"
    CAPABILITY_GAP = "CAPABILITY_GAP"
    UNKNOWN = "UNKNOWN"


@dataclass
class BrookEhrError(Exception):
    code: BrookEhrErrorCode
    ehr_name: str
    http_status: int
    message: str


# ──────────────────────────────────────────────────────────────────────────────
# Capability declaration
# ──────────────────────────────────────────────────────────────────────────────

class ShouldOperation(Enum):
    CLINICAL_SNAPSHOT = "CLINICAL_SNAPSHOT"
    UPLOAD_DOCUMENT = "UPLOAD_DOCUMENT"
    BULK_EXPORT = "BULK_EXPORT"
    SUBMIT_ORDER = "SUBMIT_ORDER"
    POST_NOTE = "POST_NOTE"
    POST_CHARGE = "POST_CHARGE"


class MayOperation(Enum):
    SUBSCRIBE = "SUBSCRIBE"


@dataclass
class AdapterCapabilities:
    ehr_name: str
    adapter_version: str
    should_ops: Set[ShouldOperation] = field(default_factory=set)
    may_ops: Set[MayOperation] = field(default_factory=set)


# ──────────────────────────────────────────────────────────────────────────────
# Exceptions
# ──────────────────────────────────────────────────────────────────────────────

class EhrAuthException(Exception):
    pass


class PatientMatchException(Exception):
    pass


class EhrOperationException(Exception):
    pass


class UnsupportedCapabilityError(NotImplementedError):
    """Raised when a SHOULD/MAY method is called on an adapter that does not implement it."""
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Base adapter
# ──────────────────────────────────────────────────────────────────────────────

class BaseEhrAdapter(ABC):
    """
    Abstract base for all Brook EHR adapters.

    MUST methods are abstract — missing implementations raise TypeError at class
    definition time. SHOULD and MAY methods raise UnsupportedCapabilityError by
    default; override them and declare them in get_capabilities().

    See: spec/adapter-contract.md for the full contract and cross-EHR matrix.
    """

    # ── MUST ──────────────────────────────────────────────────────────────────

    @abstractmethod
    def authenticate(self) -> AuthToken:
        """Authenticate with the EHR. Must handle token refresh transparently."""
        ...

    @abstractmethod
    def scope_context(self, practice_id: str, patient_id: str) -> AdapterContext:
        """Set the EHR-specific scope for subsequent calls."""
        ...

    @abstractmethod
    def match_patient(self, demographics: PatientDemographics) -> PatientMatchResult:
        """Match a patient in the EHR and return a resolved EHR-native patient ID."""
        ...

    @abstractmethod
    def get_capabilities(self) -> AdapterCapabilities:
        """Declare which SHOULD and MAY operations this adapter implements."""
        ...

    @abstractmethod
    def map_error(self, ehr_error: EhrErrorResponse) -> BrookEhrError:
        """Normalize an EHR-specific error into Brook's canonical error model."""
        ...

    @abstractmethod
    def with_idempotency_key(self, key: str, operation: Callable[[], T]) -> T:
        """Attach an idempotency key to the next outbound EHR request."""
        ...

    @abstractmethod
    def health_check(self) -> HealthCheckResult:
        """Verify connectivity to the EHR."""
        ...

    # ── SHOULD ────────────────────────────────────────────────────────────────

    def get_clinical_snapshot(self, context: AdapterContext) -> ClinicalSnapshot:
        raise UnsupportedCapabilityError(
            f"{self.__class__.__name__} does not implement get_clinical_snapshot"
        )

    def upload_document(
        self, context: AdapterContext, document: ClinicalDocument
    ) -> DocumentUploadResult:
        raise UnsupportedCapabilityError(
            f"{self.__class__.__name__} does not implement upload_document"
        )

    def initiate_bulk_export(self, context: AdapterContext) -> BulkExportJob:
        raise UnsupportedCapabilityError(
            f"{self.__class__.__name__} does not implement initiate_bulk_export"
        )

    def poll_export_status(self, job_id: str) -> BulkExportStatus:
        raise UnsupportedCapabilityError(
            f"{self.__class__.__name__} does not implement poll_export_status"
        )

    def fetch_export_content(self, manifest_url: str) -> List[NdjsonChunk]:
        raise UnsupportedCapabilityError(
            f"{self.__class__.__name__} does not implement fetch_export_content"
        )

    def submit_order(self, context: AdapterContext, order: Order) -> OrderResult:
        raise UnsupportedCapabilityError(
            f"{self.__class__.__name__} does not implement submit_order"
        )

    def get_order_status(self, order_id: str) -> OrderStatus:
        raise UnsupportedCapabilityError(
            f"{self.__class__.__name__} does not implement get_order_status"
        )

    def post_note(self, context: AdapterContext, note: ClinicalNote) -> NoteResult:
        raise UnsupportedCapabilityError(
            f"{self.__class__.__name__} does not implement post_note"
        )

    def post_charge(self, context: AdapterContext, charge: Charge) -> ChargeResult:
        raise UnsupportedCapabilityError(
            f"{self.__class__.__name__} does not implement post_charge"
        )

    # ── MAY ───────────────────────────────────────────────────────────────────

    def subscribe(self, topic: str, callback_url: str) -> SubscriptionResult:
        raise UnsupportedCapabilityError(
            f"{self.__class__.__name__} does not implement subscribe"
        )

    def unsubscribe(self, subscription_id: str) -> None:
        raise UnsupportedCapabilityError(
            f"{self.__class__.__name__} does not implement unsubscribe"
        )
