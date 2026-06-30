// PROPOSAL — not a PR. For Brook Backend team review.
// FHIR R4 mapping: Observation (https://hl7.org/fhir/R4/observation.html)
//   with category = vital-signs
// Pattern source: PersonaDiagnosis.java (PAI-184) and Activity.java
//   (src/main/java/ai/brook/data/activity/Activity.java — existing device vitals store)
// Mongo collection: persona_vitals (NEW — option A; see DESIGN NOTE below)
//
// DESIGN NOTE (CRITICAL DECISION PENDING):
// Brook's existing `activity` collection already stores device-sourced vitals
// (BP from Bodytrace/Withings, weight from connected scales, glucose from glucometers).
// ActivitySource.SourceType (src/main/java/ai/brook/data/activity/ActivitySource.java)
// defines device sources but does NOT include ATHENA_CCDA or ATHENA_BULK_FHIR.
//
// There are two valid approaches:
//
// OPTION A (this class): New `persona_vitals` collection for EHR-sourced historical
//   vitals. Clean FHIR separation, no risk of corrupting RPM billing queries.
//   Requires a new display path in POCAR.
//
// OPTION B (extend activity): Add ATHENA_CCDA / ATHENA_BULK_FHIR to
//   ActivitySource.SourceType enum. EHR vitals become activities. Lower friction,
//   reuses existing billing/display code. Risk: RPM billing DAOs assume activity =
//   device readings — dbt models and monitoring_time_raw queries may not filter by
//   source, causing EHR-historical vitals to pollute RPM billing calculations.
//
// The Backend team must resolve this before Phase 1a begins.
// See: data-model-gaps.md — Persistence Decision Question #3.
//
// This class is drafted for OPTION A. If OPTION B is chosen, only the enum extension
// in ActivitySource.SourceType is needed (not this class).

package ai.brook.data.persona.vital;

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
 * EHR-sourced vital signs observation for a patient.
 *
 * <p>FHIR R4 maps to: {@code Observation} resource with
 * {@code category = vital-signs}.</p>
 *
 * <p>Common vital sign LOINC codes relevant to Brook's population:
 * <ul>
 *   <li>Systolic BP — LOINC 8480-6</li>
 *   <li>Diastolic BP — LOINC 8462-4</li>
 *   <li>Body weight — LOINC 29463-7</li>
 *   <li>BMI — LOINC 39156-5</li>
 *   <li>Heart rate — LOINC 8867-4</li>
 *   <li>Body temperature — LOINC 8310-5</li>
 *   <li>Oxygen saturation — LOINC 2708-6</li>
 *   <li>Blood glucose (fasting) — LOINC 1558-6</li>
 * </ul>
 * </p>
 *
 * <p>IMPORTANT distinction from Brook `activity` collection:
 * This collection stores EHR-sourced historical vitals (nurse-recorded in clinic,
 * or pulled from EHR via CCDA/Bulk FHIR). The {@code activity} collection stores
 * device-sourced RPM readings (patient home monitoring for billing). These are
 * clinically distinct and should not be mixed.</p>
 *
 * <p>Key FHIR Observation fields covered:
 * {@code code} (→ loincCode + displayName),
 * {@code subject} (→ personaId),
 * {@code status} (→ status),
 * {@code effectiveDateTime} (→ effectiveAt),
 * {@code valueQuantity} (→ value + unit),
 * {@code component[]} (→ for BP panel with systolic + diastolic),
 * {@code performer} (→ performerName),
 * {@code interpretation} (→ interpretation).</p>
 */
@Getter
@Setter
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
@Document(collection = PersonaVital.COLLECTION_NAME)
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
public class PersonaVital {

    public static final String COLLECTION_NAME = "persona_vitals";

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
    private String providerOfficeId; // FK → provider_office._id (clinic where vital was recorded)

    // ──────────────────────────────────────────────────────────────
    // Source tracking
    // ──────────────────────────────────────────────────────────────

    @Field("source")
    private VitalSource source;

    @Nullable
    @Field("source_observation_id")
    private String sourceObservationId; // EHR-assigned observation ID for dedup

    // ──────────────────────────────────────────────────────────────
    // FHIR Observation.code — what vital sign was measured
    // ──────────────────────────────────────────────────────────────

    @Nullable
    @Field("loinc_code")
    private String loincCode;
    // LOINC code (e.g., "8480-6" for systolic BP). May be a panel code (e.g., BP panel 55284-4).

    @Field("display_name")
    private String displayName;
    // Human-readable vital name (e.g., "Systolic blood pressure", "Body weight").

    // ──────────────────────────────────────────────────────────────
    // FHIR Observation.status
    // ──────────────────────────────────────────────────────────────

    @Field("status")
    private ObservationStatus status;

    // ──────────────────────────────────────────────────────────────
    // FHIR Observation.effective[x] — when measured
    // ──────────────────────────────────────────────────────────────

    @Field("effective_at")
    private Instant effectiveAt;
    // When the vital sign was recorded (e.g., office visit date).

    // ──────────────────────────────────────────────────────────────
    // FHIR Observation.value[x] — the measurement
    // For single-component vitals (weight, heart rate, O2 sat, temp).
    // For multi-component vitals (BP), use components[] below.
    // ──────────────────────────────────────────────────────────────

    @Nullable
    @Field("value")
    private Double value;

    @Nullable
    @Field("value_unit")
    private String valueUnit;
    // UCUM unit preferred (e.g., "mm[Hg]", "kg", "[lb_av]", "/min", "%", "Cel", "[degF]")

    // ──────────────────────────────────────────────────────────────
    // FHIR Observation.component[] — for panel vitals (e.g., blood pressure)
    // A BP record should use components: systolic (8480-6) + diastolic (8462-4).
    // Single-value vitals leave components null.
    // ──────────────────────────────────────────────────────────────

    @Nullable
    @Field("components")
    private java.util.List<VitalComponent> components;

    // ──────────────────────────────────────────────────────────────
    // Interpretation
    // ──────────────────────────────────────────────────────────────

    @Nullable
    @Field("interpretation")
    private String interpretation;
    // HL7 ObservationInterpretation code (e.g., "H" = High, "L" = Low, "N" = Normal)

    // ──────────────────────────────────────────────────────────────
    // Performer context
    // ──────────────────────────────────────────────────────────────

    @Nullable
    @Field("performer_name")
    private String performerName;
    // Provider or nurse who recorded the vital sign (snapshotted from EHR)

    @Nullable
    @Field("encounter_id")
    private String encounterId;
    // FK → persona_encounters._id (if this vital was part of an encounter)
    // Null if standalone observation not tied to a specific encounter record.

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
    // Nested types
    // ──────────────────────────────────────────────────────────────

    /**
     * A component of a multi-part vital sign panel (e.g., BP systolic/diastolic).
     * FHIR: Observation.component
     */
    @Getter
    @Setter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public static class VitalComponent {

        @Nullable
        @Field("loinc_code")
        private String loincCode; // Component LOINC (e.g., "8480-6" for systolic)

        @Field("display_name")
        private String displayName; // e.g., "Systolic blood pressure"

        @Nullable
        @Field("value")
        private Double value; // Numeric value

        @Nullable
        @Field("value_unit")
        private String valueUnit; // e.g., "mm[Hg]"
    }

    // ──────────────────────────────────────────────────────────────
    // Enums
    // ──────────────────────────────────────────────────────────────

    /**
     * Origin of this vital signs record.
     *
     * <p>If OPTION B (extend activity) is chosen instead of this collection,
     * these values would be added to {@code ActivitySource.SourceType} enum at:
     * src/main/java/ai/brook/data/activity/ActivitySource.java</p>
     */
    public enum VitalSource {
        ATHENA_CCDA,       // From athena CCDA vital signs section (Phase 1a)
        ATHENA_BULK_FHIR,  // From athena Bulk FHIR Observation resource (Phase 3)
        REDOX,             // Received via Redox (future)
        MANUAL,            // Entered manually by care team
        OTHER
    }

    /** FHIR Observation.status value set (R4). */
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
