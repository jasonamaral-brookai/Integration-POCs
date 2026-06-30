// PROPOSAL — not a PR. For Brook Backend team review.
// FHIR R4 mapping: Condition (https://hl7.org/fhir/R4/condition.html)
//   with category = problem-list-item
// Pattern source: PersonaDiagnosis.java (PAI-184) — this class is intentionally
//   thin because the Backend team must decide whether to route CCDA problem list
//   entries directly to persona.diagnoses[] (PersonaDiagnosis with source=ATHENA_CCDA)
//   or maintain a separate PersonaProblem collection.
// See: data-model-gaps.md — Persistence Decision Question #1.
//
// DESIGN NOTE (CRITICAL): This class drafts the "maintain a separate collection"
// option. If the Backend/DNA team decides that persona.diagnoses[] IS the canonical
// store for all conditions including problem-list-items, then:
//   (a) This class is NOT needed.
//   (b) The integration layer should write CCDA problem list entries to
//       PersonaDiagnosisService with source=ATHENA_CCDA and category=PROBLEM_LIST.
//   (c) A "category" field should be added to PersonaDiagnosis to distinguish
//       problem-list vs encounter-diagnosis vs health-concern.
//
// The Backend team must make this call before Phase 1a begins.

package ai.brook.data.persona.problem;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.annotation.Id;
import org.springframework.data.annotation.LastModifiedDate;
import org.springframework.data.mongodb.core.index.CompoundIndex;
import org.springframework.data.mongodb.core.index.CompoundIndexes;
import org.springframework.data.mongodb.core.mapping.Document;
import org.springframework.data.mongodb.core.mapping.Field;

import javax.annotation.Nullable;
import java.time.Instant;

/**
 * EHR-sourced problem list entry for a patient.
 *
 * <p>FHIR R4 maps to: {@code Condition} resource with
 * {@code category = problem-list-item}.</p>
 *
 * <p>In FHIR, the Condition resource is used for both encounter-diagnosis
 * (category: encounter-diagnosis) and problem-list entries
 * (category: problem-list-item). Brook currently has {@code PersonaDiagnosis}
 * (PAI-184) for ICD-10-coded conditions — this class covers the case where
 * CCDA problem list entries need a separate storage pathway. See design note above.</p>
 *
 * <p>Key FHIR Condition fields covered: {@code code} (→ icd10Code + displayName),
 * {@code subject} (→ personaId), {@code clinicalStatus} (→ clinicalStatus),
 * {@code verificationStatus} (→ verificationStatus), {@code category}
 * (hardcoded: problem-list-item), {@code onsetDateTime} (→ onsetDate),
 * {@code abatementDateTime} (→ abatementDate), {@code recordedDate} (→ ingestedAt).</p>
 */
@Getter
@Setter
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
@Document(collection = PersonaProblem.COLLECTION_NAME)
@CompoundIndexes({
        @CompoundIndex(
                name = "persona_status",
                def = "{ 'persona_id': 1, 'clinical_status': 1 }"
        ),
        @CompoundIndex(
                name = "persona_source_ref",
                def = "{ 'persona_id': 1, 'source': 1, 'source_problem_id': 1 }",
                sparse = true,
                unique = true
        )
})
public class PersonaProblem {

    public static final String COLLECTION_NAME = "persona_problems";

    // ──────────────────────────────────────────────────────────────
    // Identity
    // ──────────────────────────────────────────────────────────────

    @Id
    @Field("_id")
    private String id; // Brook-generated UUID

    @Field("persona_id")
    private String personaId; // FK → persona._id

    @Nullable
    @Field("provider_office_id")
    private String providerOfficeId; // FK → provider_office._id

    // ──────────────────────────────────────────────────────────────
    // Source tracking
    // ──────────────────────────────────────────────────────────────

    @Field("source")
    private ProblemSource source;

    @Nullable
    @Field("source_problem_id")
    private String sourceProblemId; // EHR-assigned problem ID

    // ──────────────────────────────────────────────────────────────
    // FHIR Condition core (problem-list-item category)
    // ──────────────────────────────────────────────────────────────

    // FHIR Condition.category is always "problem-list-item" for this class.
    // No field needed — it is a type-level invariant.

    @Field("icd10_code")
    private String icd10Code;
    // FHIR Condition.code.coding[system=ICD-10-CM].code
    // Required — CCDA problem list entries include ICD-10 codes.

    @Nullable
    @Field("snomed_code")
    private String snomedCode;
    // FHIR Condition.code.coding[system=SNOMED-CT].code
    // Optional — CCDA may include SNOMED alongside ICD-10.

    @Field("display_name")
    private String displayName;
    // Human-readable condition name. Snapshotted from EHR at ingest.
    // FHIR Condition.code.text

    @Field("clinical_status")
    private ClinicalStatus clinicalStatus;
    // FHIR Condition.clinicalStatus: active | recurrence | relapse | inactive | remission | resolved

    @Field("verification_status")
    private VerificationStatus verificationStatus;
    // FHIR Condition.verificationStatus: unconfirmed | provisional | differential | confirmed | refuted

    @Nullable
    @Field("onset_date")
    private Instant onsetDate;
    // FHIR Condition.onsetDateTime — when the problem started

    @Nullable
    @Field("abatement_date")
    private Instant abatementDate;
    // FHIR Condition.abatementDateTime — when the problem resolved/ended

    // ──────────────────────────────────────────────────────────────
    // Audit
    // ──────────────────────────────────────────────────────────────

    @Field("ingested_at")
    @CreatedDate
    private Instant ingestedAt;

    @Nullable
    @Field("updated_at")
    @LastModifiedDate
    private Instant updatedAt;

    // ──────────────────────────────────────────────────────────────
    // Enums
    // ──────────────────────────────────────────────────────────────

    /**
     * Origin of this problem list entry. Pattern matches DiagnosisSource (PAI-184).
     */
    public enum ProblemSource {
        ATHENA_CCDA,
        ATHENA_BULK_FHIR,
        REDOX,
        MANUAL,
        OTHER
    }

    /**
     * FHIR Condition.clinicalStatus value set (R4).
     * See: https://hl7.org/fhir/R4/valueset-condition-clinical.html
     */
    public enum ClinicalStatus {
        ACTIVE,
        RECURRENCE,
        RELAPSE,
        INACTIVE,
        REMISSION,
        RESOLVED
    }

    /**
     * FHIR Condition.verificationStatus value set (R4).
     * See: https://hl7.org/fhir/R4/valueset-condition-ver-status.html
     */
    public enum VerificationStatus {
        UNCONFIRMED,
        PROVISIONAL,
        DIFFERENTIAL,
        CONFIRMED,
        REFUTED,
        ENTERED_IN_ERROR
    }
}
