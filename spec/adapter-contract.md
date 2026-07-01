# Brook EHR Adapter Contract

**PROPOSAL — not a PR. For Brook Backend team review.**

This document defines the interface contract for all EHR adapters in the Brook integration
platform. Every EHR (athena, Epic, Cerner, NextGen) is implemented as an adapter that
satisfies this contract. The contract is capability-tiered: MUST operations are required
of all adapters, SHOULD operations are expected for production partners, and MAY operations
are optional.

The Java interface below is the authoritative signature. The arch-poc
(`arch-poc/integration_layer/base_adapter.py`) provides a Python implementation
of the same contract for local testing without brook-backend.

---

## Capability Tiers

| Tier | Meaning | Brook enforcement |
|------|---------|------------------|
| MUST | Required for any adapter to be registered | Compile-time (abstract methods) |
| SHOULD | Expected for production partners; absence logged as capability gap | Runtime via `getCapabilities()` |
| MAY | Optional; enables advanced platform features if present | Runtime feature detection |

---

## Java Interface

```java
package ai.brook.integration.adapter;

import java.util.List;
import java.util.function.Supplier;

/**
 * Contract for all Brook EHR adapters.
 *
 * MUST operations are abstract — any adapter that does not implement them
 * will not compile. SHOULD and MAY operations have default implementations
 * that throw UnsupportedCapabilityException, and must be declared in
 * getCapabilities() if overridden.
 *
 * Adapters are Spring @Component singletons. They must be stateless with
 * respect to per-request context — all context is passed as method arguments.
 */
public interface EhrAdapter {

    // ══════════════════════════════════════════════════════════════════
    // MUST — Required of all adapters
    // ══════════════════════════════════════════════════════════════════

    /**
     * Authenticate with the EHR and return a valid token.
     * Implementations must handle token refresh transparently.
     * Called before any SHOULD/MAY operation.
     *
     * athena: OAuth2 client credentials
     *   POST /oauth2/v1/token (client_id, client_secret)
     * Epic / Cerner: SMART on FHIR backend service auth
     */
    AuthToken authenticate() throws EhrAuthException;

    /**
     * Set the EHR-specific scope for subsequent calls: which practice,
     * which patient. Returns an opaque context object passed to all
     * SHOULD/MAY operations.
     *
     * athena: practiceId scopes all API calls; required in URL path.
     * Epic: Organization FHIR ID + Patient FHIR ID.
     */
    AdapterContext scopeContext(String practiceId, String patientId);

    /**
     * Match a patient in the EHR by demographics and return a resolved
     * EHR-native patient identifier (e.g., athena patientid, Epic FHIR ID).
     *
     * athena: POST /v1/{practiceid}/patients/enterprisepatientlookup
     * Epic/Cerner: FHIR Patient/$match
     */
    PatientMatchResult matchPatient(PatientDemographics demographics)
            throws PatientMatchException;

    /**
     * Declare which SHOULD and MAY operations this adapter implements.
     * Called at startup and when the platform needs to route operations.
     *
     * Example: AthenaAdapter.getCapabilities() returns
     *   shouldOps = {CLINICAL_SNAPSHOT, UPLOAD_DOCUMENT, BULK_EXPORT,
     *                SUBMIT_ORDER, POST_NOTE, POST_CHARGE}
     *   mayOps    = {SUBSCRIBE}
     */
    AdapterCapabilities getCapabilities();

    /**
     * Normalize an EHR-specific error response into Brook's canonical
     * error model. All SHOULD/MAY operations must pass their exceptions
     * through mapError before propagating up the stack.
     *
     * athena: maps HTTP 429 → RATE_LIMITED, 404 → NOT_FOUND,
     *         400 w/ "INVALID_PATIENT" body → PATIENT_NOT_FOUND, etc.
     */
    BrookEhrError mapError(EhrErrorResponse ehrError);

    /**
     * Attach an idempotency key to the next outbound EHR request.
     * Returns the result of the supplied operation with the key applied.
     *
     * athena: sent as X-Idempotency-Key request header.
     * Key format: {patientId}:{operationType}:{eventVersion}
     *
     * The key must be stored in EmrLog before the operation fires so that
     * a crash between key generation and request send is recoverable.
     */
    <T> T withIdempotencyKey(String key, Supplier<T> operation)
            throws EhrOperationException;

    /**
     * Verify connectivity to the EHR. Returns latency and auth status.
     * Used by Integration Health Dashboard and startup readiness checks.
     *
     * athena: GET /v1/{practiceid}/departments?limit=1 (cheapest authenticated call)
     */
    HealthCheckResult healthCheck();

    // ══════════════════════════════════════════════════════════════════
    // SHOULD — Expected for production partners
    // Default throws UnsupportedCapabilityException.
    // Override AND declare in getCapabilities().
    // ══════════════════════════════════════════════════════════════════

    /**
     * Retrieve a clinical snapshot (C-CDA or FHIR equivalent) for a patient
     * and return it as a structured payload for the mapping layer.
     *
     * athena (Phase 1a):
     *   GET /v1/{practiceid}/ccda/{patientid}/ccda
     *   Returns C-CDA R2.1 XML. Sections: problems (11450-4), medications
     *   (10160-0), encounters (46240-8), allergies (48765-2), labs (30954-2),
     *   vitals (8716-3).
     *
     * Epic/Cerner: FHIR Patient/$everything or individual resource queries.
     */
    default ClinicalSnapshot getClinicalSnapshot(AdapterContext context)
            throws UnsupportedCapabilityException {
        throw new UnsupportedCapabilityException(
            getClass().getSimpleName() + " does not implement getClinicalSnapshot");
    }

    /**
     * Upload a clinical document to the EHR on behalf of a patient.
     *
     * athena (P1b — live today, needs refactor):
     *   POST /v1/{practiceid}/patients/{patientid}/documents/clinicaldocument
     *   documentTypeId and documentsubclass read from mapping config (not hardcoded).
     *
     * Idempotency key: {patientId}:{documentType}:{eventVersion}
     */
    default DocumentUploadResult uploadDocument(
            AdapterContext context,
            ClinicalDocument document)
            throws UnsupportedCapabilityException {
        throw new UnsupportedCapabilityException(
            getClass().getSimpleName() + " does not implement uploadDocument");
    }

    /**
     * Initiate an async Bulk FHIR export job for population-level data.
     *
     * athena (Phase 3):
     *   POST /fhir/r4/Group/{groupId}/$export
     *   Returns a Content-Location URL for polling.
     *
     * Returns a jobId for use with pollExportStatus().
     */
    default BulkExportJob initiateBulkExport(AdapterContext context)
            throws UnsupportedCapabilityException {
        throw new UnsupportedCapabilityException(
            getClass().getSimpleName() + " does not implement initiateBulkExport");
    }

    /**
     * Poll the status of a Bulk FHIR export job.
     *
     * athena: GET {contentLocationUrl}
     *   202 = in progress, 200 = complete (manifest in body).
     */
    default BulkExportStatus pollExportStatus(String jobId)
            throws UnsupportedCapabilityException {
        throw new UnsupportedCapabilityException(
            getClass().getSimpleName() + " does not implement pollExportStatus");
    }

    /**
     * Fetch completed NDJSON content from a Bulk FHIR export manifest.
     *
     * athena: GET each URL in the manifest output[] array.
     *   Returns NDJSON (one FHIR resource per line).
     */
    default List<NdjsonChunk> fetchExportContent(String manifestUrl)
            throws UnsupportedCapabilityException {
        throw new UnsupportedCapabilityException(
            getClass().getSimpleName() + " does not implement fetchExportContent");
    }

    /**
     * Submit a clinical order to the EHR.
     *
     * athena (Phase 2 — postmodern model):
     *   POST /v1/{practiceid}/patients/{patientid}/orders/lab
     *   Physician signs post-hoc in athena task queue.
     *
     * Idempotency key: {patientId}:{orderId}:{orderVersion}
     */
    default OrderResult submitOrder(AdapterContext context, Order order)
            throws UnsupportedCapabilityException {
        throw new UnsupportedCapabilityException(
            getClass().getSimpleName() + " does not implement submitOrder");
    }

    /**
     * Poll the status of a submitted order.
     *
     * athena: GET /v1/{practiceid}/patients/{patientid}/orders/{orderid}
     */
    default OrderStatus getOrderStatus(String orderId)
            throws UnsupportedCapabilityException {
        throw new UnsupportedCapabilityException(
            getClass().getSimpleName() + " does not implement getOrderStatus");
    }

    /**
     * Post a clinical note to the EHR for a patient.
     *
     * athena (Phase 4):
     *   POST /v1/{practiceid}/patients/{patientid}/notes
     *   AthenaService does not implement sendPatientNote() today — greenfield.
     */
    default NoteResult postNote(AdapterContext context, ClinicalNote note)
            throws UnsupportedCapabilityException {
        throw new UnsupportedCapabilityException(
            getClass().getSimpleName() + " does not implement postNote");
    }

    /**
     * Post a real-time billing charge to the EHR.
     *
     * athena (Phase 5):
     *   POST /v1/{practiceid}/charges
     *   CPT code and modifier read from mapping config per program type.
     *
     * Idempotency key: {patientId}:{encounterId}:{cptCode}:{eventVersion}
     */
    default ChargeResult postCharge(AdapterContext context, Charge charge)
            throws UnsupportedCapabilityException {
        throw new UnsupportedCapabilityException(
            getClass().getSimpleName() + " does not implement postCharge");
    }

    // ══════════════════════════════════════════════════════════════════
    // MAY — Optional; enables advanced platform features
    // ══════════════════════════════════════════════════════════════════

    /**
     * Subscribe to EHR push notifications for a topic.
     *
     * athena: FHIR Subscriptions (alpha as of 2026).
     *   POST /fhir/r4/Subscription
     *   Topics: patient-data-change, appointment-change, order-signed.
     *   Requires athena FHIR alpha API access — not GA.
     *
     * Returns a subscriptionId for use with unsubscribe().
     */
    default SubscriptionResult subscribe(String topic, String callbackUrl)
            throws UnsupportedCapabilityException {
        throw new UnsupportedCapabilityException(
            getClass().getSimpleName() + " does not implement subscribe");
    }

    /**
     * Cancel an active EHR subscription.
     *
     * athena: DELETE /fhir/r4/Subscription/{subscriptionId}
     */
    default void unsubscribe(String subscriptionId)
            throws UnsupportedCapabilityException {
        throw new UnsupportedCapabilityException(
            getClass().getSimpleName() + " does not implement unsubscribe");
    }
}
```

---

## AdapterCapabilities Contract

`getCapabilities()` returns this object at startup. The platform uses it to route
operations and to detect missing capabilities before attempting calls.

```java
public class AdapterCapabilities {
    private final String ehrName;           // "athena" | "epic" | "cerner" | "nextgen"
    private final String adapterVersion;    // semver string
    private final Set<ShouldOperation> shouldOps;
    private final Set<MayOperation> mayOps;

    public enum ShouldOperation {
        CLINICAL_SNAPSHOT,
        UPLOAD_DOCUMENT,
        BULK_EXPORT,
        SUBMIT_ORDER,
        POST_NOTE,
        POST_CHARGE
    }

    public enum MayOperation {
        SUBSCRIBE
    }
}
```

---

## Error Normalization Contract

`mapError()` normalizes EHR-specific HTTP errors into Brook's canonical error type.
All SHOULD/MAY operation implementations must call `mapError` before rethrowing.

```java
public class BrookEhrError extends RuntimeException {
    public enum ErrorCode {
        RATE_LIMITED,         // HTTP 429 — caller should apply backoff
        NOT_FOUND,            // HTTP 404 — resource does not exist
        PATIENT_NOT_FOUND,    // EHR-specific patient lookup failure
        AUTH_FAILED,          // HTTP 401/403 — token invalid or expired
        VALIDATION_ERROR,     // HTTP 400 — malformed request payload
        TRANSIENT,            // HTTP 5xx — retry eligible
        CAPABILITY_GAP,       // Operation not supported by this adapter version
        UNKNOWN               // Catch-all — escalate to Integration Health Dashboard
    }

    private final ErrorCode code;
    private final String ehrName;
    private final int httpStatus;
    private final String rawBody;
}
```

**athena error mapping table:**

| athena HTTP status | athena body signal | BrookEhrError.code |
|-------------------|-------------------|---------------------|
| 429 | any | RATE_LIMITED |
| 404 | any | NOT_FOUND |
| 400 | `"INVALID_PATIENT"` | PATIENT_NOT_FOUND |
| 400 | other | VALIDATION_ERROR |
| 401 | any | AUTH_FAILED |
| 403 | any | AUTH_FAILED |
| 500, 502, 503 | any | TRANSIENT |
| other | any | UNKNOWN |

---

## Cross-EHR Support Matrix

| Operation | Tier | athena v1 | Epic | Cerner | NextGen |
|-----------|------|-----------|------|--------|---------|
| `authenticate()` | MUST | OAuth2 client credentials | SMART on FHIR backend | SMART on FHIR backend | API key |
| `scopeContext()` | MUST | practiceId + patientId | Org FHIR ID + Patient FHIR ID | Tenant ID + Patient FHIR ID | Practice ID |
| `matchPatient()` | MUST | Enterprise patient lookup | FHIR Patient/$match | FHIR Patient/$match | Patient search |
| `getCapabilities()` | MUST | All SHOULD + SUBSCRIBE | CLINICAL_SNAPSHOT, UPLOAD_DOCUMENT | CLINICAL_SNAPSHOT | TBD |
| `mapError()` | MUST | See table above | FHIR OperationOutcome | FHIR OperationOutcome | Proprietary |
| `withIdempotencyKey()` | MUST | X-Idempotency-Key header | Request-ID header | Not native — log-side | Not native — log-side |
| `healthCheck()` | MUST | GET /departments?limit=1 | GET /metadata | GET /metadata | Ping |
| `getClinicalSnapshot()` | SHOULD | CCDA GET (Phase 1a) | FHIR Patient/$everything | FHIR Patient/$everything | CCDA |
| `uploadDocument()` | SHOULD | POST /clinicaldocument (P1b — live) | FHIR DocumentReference | FHIR DocumentReference | Proprietary |
| `initiateBulkExport()` | SHOULD | FHIR Group/$export (Phase 3) | FHIR Group/$export | FHIR Group/$export | Not supported |
| `pollExportStatus()` | SHOULD | Content-Location poll (Phase 3) | Content-Location poll | Content-Location poll | N/A |
| `fetchExportContent()` | SHOULD | NDJSON download (Phase 3) | NDJSON download | NDJSON download | N/A |
| `submitOrder()` | SHOULD | POST /orders/lab (Phase 2) | FHIR ServiceRequest | FHIR ServiceRequest | Proprietary |
| `getOrderStatus()` | SHOULD | GET /orders/{id} (Phase 2) | FHIR ServiceRequest | FHIR ServiceRequest | Proprietary |
| `postNote()` | SHOULD | POST /notes (Phase 4) | FHIR DocumentReference | FHIR DocumentReference | Proprietary |
| `postCharge()` | SHOULD | POST /charges (Phase 5) | FHIR Claim | Not supported | Proprietary |
| `subscribe()` | MAY | FHIR Subscriptions (alpha) | FHIR Subscriptions (R4B) | Not GA | Not supported |
| `unsubscribe()` | MAY | DELETE /Subscription/{id} (alpha) | DELETE /Subscription/{id} | N/A | N/A |

Legend: Phase N = brook integration platform phase; "live" = shipping today in brook-backend.

---

## Implementation Guide: Adding a New EHR Adapter

1. Create `src/main/java/ai/brook/integration/adapter/{ehr}/` package.
2. Implement `EhrAdapter` — all MUST methods are required to compile.
3. Override SHOULD methods for operations the EHR supports; leave others as default.
4. Implement `getCapabilities()` to declare exactly which SHOULD/MAY methods you override.
5. Annotate the class with `@Component` and `@Qualifier("{ehr}Adapter")`.
6. Add the EHR name to the cross-EHR support matrix in this document.
7. Create a mapping config file at `config/mapping/{ehr}.yaml` (or `.json` per Decision 8).
8. Wire the adapter into `AdapterRegistry` — the platform uses `getCapabilities()` to
   select the right adapter and operation at runtime.

**Do not** hardcode partner-specific values (documentTypeId, practice IDs, CPT codes)
in the adapter class. All partner-specific values belong in the mapping config file.

---

## Related tickets

| Ticket | Operation | Phase |
|--------|-----------|-------|
| PAI-416 | `withIdempotencyKey()` — ExponentialBackoffInterceptor wiring | P0 |
| PAI-430 | Event bus contract (events emitted after each SHOULD operation) | P0 |
| PAI-431 | Mapping config schema (feeds all SHOULD operations) | P0 |
| PAI-432 | `authenticate()` — auth scaffolding audit | P0 |
| PAI-433 | `getClinicalSnapshot()` — CCDA retrieval | P1a |
| PAI-435 | CCDA entity adapters (consume getClinicalSnapshot output) | P1a |
| PAI-438 | `uploadDocument()` — mapping config migration | P1b |
| PAI-441 | `submitOrder()` — clinician workflow verification | P2 |
| PAI-442 | `submitOrder()` / `getOrderStatus()` — order ingest | P2 |
