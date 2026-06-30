// PROPOSAL — not a PR. For Brook Backend team review.
// FHIR R4 mapping: AllergyIntolerance (https://hl7.org/fhir/R4/allergyintolerance.html)
// Pattern source: PersonaDiagnosis.java (PAI-184) and Allergies.java
//   (src/main/java/ai/brook/api/caremanagement/model/Allergies.java)
// Mongo collection: persona_allergies (NEW — does not exist in brook-backend as of 2026-06-30 scan)
//
// DESIGN NOTE: Brook currently stores allergies as freetext strings in
// PatientCarePlans.allergies[].allergen / .reaction. That care plan section
// is the care team's editable allergy list. This new collection receives
// EHR-sourced discrete, coded allergy records from CCDA/Bulk FHIR.
//
// CLINICAL SAFETY NOTE: Allergy data is a patient safety record. The Backend/DNA
// team must define the authoritative source policy — does EHR-sourced allergy
// data override care team data, supplement it, or require reconciliation?
// See data-model-gaps.md Open Questions.

package ai.brook.data.persona.allergy;

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
import java.util.List;

/**
 * EHR-sourced allergy or intolerance record for a patient.
 *
 * <p>FHIR R4 maps to: {@code AllergyIntolerance} resource.</p>
 *
 * <p>Key FHIR fields covered:
 * {@code patient} (→ personaId),
 * {@code clinicalStatus} (→ clinicalStatus),
 * {@code verificationStatus} (→ verificationStatus),
 * {@code type} (→ allergyType: allergy | intolerance),
 * {@code category} (→ categories[]: food | medication | environment | biologic),
 * {@code criticality} (→ criticality: low | high | unable-to-assess),
 * {@code code} (→ allergenName + rxNormCode + snomedCode),
 * {@code onsetDateTime} (→ onsetDate),
 * {@code recorder} (→ source),
 * {@code reaction[].manifestation} (→ reactions[].manifestation),
 * {@code reaction[].severity} (→ reactions[].severity).</p>
 *
 * <p>Criticality is clinically critical for medication safety decisions.
 * Do not collapse this to freetext.</p>
 */
@Getter
@Setter
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
@Document(collection = PersonaAllergy.COLLECTION_NAME)
@CompoundIndexes({
        @CompoundIndex(
                name = "persona_status",
                def = "{ 'persona_id': 1, 'clinical_status': 1 }"
        ),
        @CompoundIndex(
                name = "persona_source_ref",
                def = "{ 'persona_id': 1, 'source': 1, 'source_allergy_id': 1 }",
                sparse = true,
                unique = true
        )
})
public class PersonaAllergy {

    public static final String COLLECTION_NAME = "persona_allergies";

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
    private AllergySource source;

    @Nullable
    @Field("source_allergy_id")
    private String sourceAllergyId; // EHR-assigned allergy record ID

    // ──────────────────────────────────────────────────────────────
    // FHIR AllergyIntolerance core fields
    // ──────────────────────────────────────────────────────────────

    @Field("clinical_status")
    private ClinicalStatus clinicalStatus;
    // FHIR AllergyIntolerance.clinicalStatus: active | inactive | resolved

    @Field("verification_status")
    private VerificationStatus verificationStatus;
    // FHIR AllergyIntolerance.verificationStatus: unconfirmed | confirmed | refuted | entered-in-error

    @Nullable
    @Field("allergy_type")
    private AllergyType allergyType;
    // FHIR AllergyIntolerance.type: allergy | intolerance

    @Nullable
    @Field("categories")
    private List<AllergyCategory> categories;
    // FHIR AllergyIntolerance.category[]: food | medication | environment | biologic

    @Nullable
    @Field("criticality")
    private Criticality criticality;
    // FHIR AllergyIntolerance.criticality: low | high | unable-to-assess
    // CLINICAL SAFETY: Store this. Do not drop it.

    // ──────────────────────────────────────────────────────────────
    // Allergen coding
    // ──────────────────────────────────────────────────────────────

    @Field("allergen_name")
    private String allergenName;
    // Display name of allergen (e.g., "Penicillin", "Peanuts"). Required.
    // FHIR AllergyIntolerance.code.text

    @Nullable
    @Field("rx_norm_code")
    private String rxNormCode;
    // RxNorm code for medication allergens (most common in CCDA).
    // FHIR AllergyIntolerance.code.coding[system=rxnorm].code

    @Nullable
    @Field("snomed_code")
    private String snomedCode;
    // SNOMED CT code for non-medication allergens (e.g., food, environment).
    // FHIR AllergyIntolerance.code.coding[system=snomed-ct].code

    @Nullable
    @Field("onset_date")
    private Instant onsetDate;
    // When the allergy was first noted. FHIR AllergyIntolerance.onsetDateTime

    // ──────────────────────────────────────────────────────────────
    // Reactions
    // ──────────────────────────────────────────────────────────────

    @Nullable
    @Field("reactions")
    private List<AllergyReaction> reactions;
    // FHIR AllergyIntolerance.reaction[]

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
     * A specific allergic reaction manifestation.
     * FHIR: AllergyIntolerance.reaction
     */
    @Getter
    @Setter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public static class AllergyReaction {

        @Nullable
        @Field("manifestation")
        private String manifestation;
        // FHIR AllergyIntolerance.reaction[].manifestation.text
        // (e.g., "Hives", "Anaphylaxis"). Free text in v1; future: SNOMED coded.

        @Nullable
        @Field("manifestation_snomed_code")
        private String manifestationSnomedCode;
        // SNOMED code for reaction manifestation (optional, from CCDA when present)

        @Nullable
        @Field("severity")
        private ReactionSeverity severity;
        // FHIR AllergyIntolerance.reaction[].severity: mild | moderate | severe
    }

    // ──────────────────────────────────────────────────────────────
    // Enums
    // ──────────────────────────────────────────────────────────────

    /** Origin of this allergy record. Pattern matches DiagnosisSource (PAI-184). */
    public enum AllergySource {
        ATHENA_CCDA,
        ATHENA_BULK_FHIR,
        REDOX,
        MANUAL,
        OTHER
    }

    /** FHIR AllergyIntolerance.clinicalStatus */
    public enum ClinicalStatus {
        ACTIVE,
        INACTIVE,
        RESOLVED
    }

    /** FHIR AllergyIntolerance.verificationStatus */
    public enum VerificationStatus {
        UNCONFIRMED,
        CONFIRMED,
        REFUTED,
        ENTERED_IN_ERROR
    }

    /** FHIR AllergyIntolerance.type */
    public enum AllergyType {
        ALLERGY,
        INTOLERANCE
    }

    /** FHIR AllergyIntolerance.category */
    public enum AllergyCategory {
        FOOD,
        MEDICATION,
        ENVIRONMENT,
        BIOLOGIC
    }

    /** FHIR AllergyIntolerance.criticality */
    public enum Criticality {
        LOW,
        HIGH,
        UNABLE_TO_ASSESS
    }

    /** FHIR AllergyIntolerance.reaction[].severity */
    public enum ReactionSeverity {
        MILD,
        MODERATE,
        SEVERE
    }
}
