// PROPOSAL — not a PR. For Brook Backend team review.
// FHIR R4 mapping: Observation (https://hl7.org/fhir/R4/observation.html)
//   with category = laboratory
// Pattern source: PersonaDiagnosis.java (PAI-184) and Redox flowsheet
//   Observation.java (src/main/java/ai/brook/api/rpm/emr/redox/api/model/flowsheets/Observation.java)
// Mongo collection: persona_labs (NEW — does not exist in brook-backend as of 2026-06-30 scan)
//
// DESIGN NOTE: This is a NEW top-level collection for EHR-sourced lab results.
// Brook's existing activity collection stores device-sourced readings (A1c from
// glucometers, BP from Bodytrace etc.). EHR-sourced lab results (A1c from lab,
// GFR from lab, HbA1c ordered by physician) are a distinct data source and
// should not be conflated with device readings in the billing/monitoring pipeline.
//
// PAP flat scalars (last_a1c, last_gfr, date_of_last_a1c, date_of_gfr) represent
// single-value registration snapshots. This collection provides a historical series.
//
// See: data-model-gaps.md — Persistence Decision Question #4.

package ai.brook.data.persona.lab;

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
 * EHR-sourced laboratory result for a patient.
 *
 * <p>FHIR R4 maps to: {@code Observation} resource with
 * {@code category = laboratory}.</p>
 *
 * <p>Key clinical labs for Brook's chronic condition population:
 * <ul>
 *   <li>A1c (HbA1c) — LOINC 4548-4 or 17856-6</li>
 *   <li>eGFR — LOINC 62238-1</li>
 *   <li>Fasting glucose — LOINC 1558-6</li>
 *   <li>Lipid panel components — LOINC 2093-3 (cholesterol), 2085-9 (HDL), 13457-7 (LDL-calc)</li>
 *   <li>BNP/NT-proBNP — LOINC 42637-9 / 33762-6 (CHF monitoring)</li>
 *   <li>Creatinine — LOINC 2160-0</li>
 * </ul>
 * </p>
 *
 * <p>Key FHIR Observation fields covered:
 * {@code code} (→ loincCode + displayName),
 * {@code subject} (→ personaId),
 * {@code status} (→ status),
 * {@code effectiveDateTime} (→ effectiveAt),
 * {@code valueQuantity} (→ value + unit),
 * {@code interpretation} (→ interpretation),
 * {@code referenceRange} (→ referenceRangeLow / referenceRangeHigh + referenceRangeText),
 * {@code performer} (→ performerName / performingLabName).</p>
 */
@Getter
@Setter
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
@Document(collection = PersonaLab.COLLECTION_NAME)
@CompoundIndexes({
        @CompoundIndex(
                name = "persona_loinc_effective",
                def = "{ 'persona_id': 1, 'loinc_code': 1, 'effective_at': -1 }"
        ),
        @CompoundIndex(
                name = "persona_effective",
                def = "{ 'persona_id': 1, 'effective_at': -1 }"
        ),
        @CompoundIndex(
                name = "persona_source_ref",
                def = "{ 'persona_id': 1, 'source': 1, 'source_observation_id': 1 }",
                sparse = true,
                unique = true
        )
})
public class PersonaLab {

    public static final String COLLECTION_NAME = "persona_labs";

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
    private String providerOfficeId; // FK → provider_office._id (ordering clinic)

    // ──────────────────────────────────────────────────────────────
    // Source tracking
    // ──────────────────────────────────────────────────────────────

    @Field("source")
    private LabSource source;

    @Nullable
    @Field("source_observation_id")
    private String sourceObservationId; // EHR-assigned observation ID for dedup

    // ──────────────────────────────────────────────────────────────
    // FHIR Observation.code — what was measured
    // ──────────────────────────────────────────────────────────────

    @Nullable
    @Field("loinc_code")
    private String loincCode;
    // LOINC code (e.g., "4548-4" for A1c). Required when available from EHR.
    // FHIR Observation.code.coding[system=LOINC].code

    @Field("display_name")
    private String displayName;
    // Human-readable test name (e.g., "Hemoglobin A1c/Hemoglobin.total in Blood").
    // Required. Snapshotted from EHR. FHIR Observation.code.text

    // ──────────────────────────────────────────────────────────────
    // FHIR Observation.status
    // ──────────────────────────────────────────────────────────────

    @Field("status")
    private ObservationStatus status;
    // FHIR Observation.status: registered | preliminary | final | amended | corrected | cancelled | entered-in-error

    // ──────────────────────────────────────────────────────────────
    // FHIR Observation.effective[x] — when the specimen was collected
    // ──────────────────────────────────────────────────────────────

    @Field("effective_at")
    private Instant effectiveAt;
    // Date/time the specimen was collected or result was observed.
    // FHIR Observation.effectiveDateTime

    // ──────────────────────────────────────────────────────────────
    // FHIR Observation.value[x] — the measured result
    // ──────────────────────────────────────────────────────────────

    @Nullable
    @Field("value")
    private Double value;
    // Numeric result value (e.g., 7.2 for A1c in %).
    // FHIR Observation.valueQuantity.value

    @Nullable
    @Field("value_unit")
    private String valueUnit;
    // Unit of measure (e.g., "%", "mg/dL", "mL/min/1.73m2").
    // FHIR Observation.valueQuantity.unit (UCUM preferred)

    @Nullable
    @Field("value_string")
    private String valueString;
    // Freetext result for non-numeric values (e.g., "Detected", "Negative").
    // FHIR Observation.valueString — used when value is not numeric.

    // ──────────────────────────────────────────────────────────────
    // FHIR Observation.interpretation — normal/abnormal flag
    // ──────────────────────────────────────────────────────────────

    @Nullable
    @Field("interpretation")
    private String interpretation;
    // Interpretation code from EHR (e.g., "H" = High, "L" = Low, "N" = Normal, "A" = Abnormal, "AA" = Critical).
    // FHIR Observation.interpretation.coding[].code (HL7 v3 ObservationInterpretation code system)

    // ──────────────────────────────────────────────────────────────
    // FHIR Observation.referenceRange — lab normal range
    // ──────────────────────────────────────────────────────────────

    @Nullable
    @Field("reference_range_low")
    private Double referenceRangeLow;

    @Nullable
    @Field("reference_range_high")
    private Double referenceRangeHigh;

    @Nullable
    @Field("reference_range_text")
    private String referenceRangeText;
    // Free text range (e.g., "< 5.7%") when numeric bounds are not parseable.

    // ──────────────────────────────────────────────────────────────
    // FHIR Observation.performer — who reported the result
    // ──────────────────────────────────────────────────────────────

    @Nullable
    @Field("performing_lab_name")
    private String performingLabName;
    // Name of the laboratory that performed the test (e.g., "Quest Diagnostics").

    @Nullable
    @Field("performer_name")
    private String performerName;
    // Ordering/reporting provider name (snapshotted from EHR).

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
     * Origin of this lab result. Pattern matches DiagnosisSource (PAI-184).
     */
    public enum LabSource {
        ATHENA_CCDA,       // From athena CCDA laboratory results section (Phase 1a)
        ATHENA_BULK_FHIR,  // From athena Bulk FHIR Observation resource (Phase 3)
        REDOX,             // Received via Redox (future)
        MANUAL,            // Entered manually by care team
        OTHER
    }

    /**
     * FHIR Observation.status value set (R4).
     * See: https://hl7.org/fhir/R4/valueset-observation-status.html
     */
    public enum ObservationStatus {
        REGISTERED,
        PRELIMINARY,
        FINAL,
        AMENDED,
        CORRECTED,
        CANCELLED,
        ENTERED_IN_ERROR,
        UNKNOWN
    }
}
