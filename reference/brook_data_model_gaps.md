# Brook Data Model Reference

## MongoDB (brook-backend)

### Profile
**File:** `src/main/java/ai/brook/data/persona/Profile.java`
**Collection:** embedded superclass of Persona; no `@Document` annotation

| Field | Type | Notes |
|---|---|---|
| lastName | String | stored as `last_name` |
| gender | String | stored as `gender` |
| imageId | String | stored as `imageid`; @Nullable |
| imageUrl | String | stored as `image_url`; @Nullable |
| verifyEmailToken | String | stored as `verify_email_token`; @JsonIgnore |
| height | Number | stored as `height`; @Nullable |
| otherConditions | String | stored as `other_conditions` |
| isVerified | Boolean | stored as `is_verified` |
| activationDate | Date | stored as `activation_date`; @Nullable |
| usesTracker | Boolean | stored as `uses_tracker` |
| hadCheckup | Boolean | stored as `had_checkup` |
| takesMedication | Boolean | stored as `takes_medication` |
| takesFluVaccine | Boolean | stored as `takes_flu_vaccine` |
| shouldRequestPermissions | Boolean | stored as `permissions_request` |
| address | Address | stored as `mailing_address` |
| phoneNumber | String | stored as `phone_number` |
| homePhoneNumber | String | stored as `home_phone_number`; @Nullable |
| phoneNumberType | PhoneNumberType | stored as `phone_number_type`; @Nullable |
| units | Units | stored as `units`; @Nullable |
| firstName | String | stored as `first_name` |
| alias | String | stored as `alias_name` |
| uniqueUserKey | String | stored as `unique_user_key`; @Indexed(name="unique_user_key") |
| email | String | stored as `email`; normalized to lowercase on set |
| dateOfBirth | Date | stored as `dob`; @JsonFormat(pattern="yyyy-MM-dd") |
| permissions | Permissions | stored as `permissions` |
| featurePermissions | FeaturePermissions | stored as `feature_permissions` |
| conditions | Set\<Condition\> | stored as `conditions` |
| professionalTitles | String | stored as `professional_titles` |
| billing99091 | Boolean | stored as `billing_99091` |
| billing99457and99458 | Boolean | stored as `billing_99457_and_99458` |
| carePlanReviewer | Boolean | stored as `care_plan_reviewer` |
| nickname | String | stored as `nickname` |
| psmAssigned | String | stored as `psm_assigned` |
| eligibleForEmailReports | Boolean | stored as `eligible_for_email_reports` |
| providerEnabledFeatures | Set\<String\> | stored as `provider_enabled_features` |
| homeClinicId | String | stored as `home_clinic_id`; @Nullable |
| isProvider | Boolean | stored as `is_provider` |
| providerDetails | ProviderDetails | stored as `provider_details`; @Nullable |
| currentConsents | List\<CurrentConsent\> | @Transient; @Nullable |
| lastHistoricalConsents | List\<HistoricalConsent\> | @Transient; @Nullable |
| initialWeight | Double | stored as `initial_weight`; @Nullable |
| isProviderReferral | Boolean | stored as `is_provider_referral`; @Nullable |
| providerReferralDate | Date | stored as `provider_referral_date`; @Nullable |
| lowTech | Boolean | stored as `low_tech`; @Nullable |
| acoParticipant | Boolean | stored as `aco_participant`; @Nullable |
| usesApps | Boolean | stored as `uses_apps`; @Nullable |
| legacyInfo | LegacyInfo | stored as `legacy_info`; @Deprecated; @Nullable |

---

### Persona
**File:** `src/main/java/ai/brook/data/persona/Persona.java`
**Collection:** `persona`

Extends Profile (inherits all Profile fields above).

```
@CompoundIndex persona_patient_office:
  { legacy_persona_id: 1, 'provider_details.patient_provider_office_id': 1 }
  sparse=true, unique=true

@CompoundIndex patient_provider_office_id:
  { 'provider_details.patient_provider_office_id': 1 }
  partialFilter exists

@CompoundIndex provider_office_ids.0:
  { 'provider_details.provider_office_ids.0': 1 }
  sparse=true

@CompoundIndex mrn:
  { 'provider_details.mrn': 1 }
  partialFilter exists

@CompoundIndex secondary_clinics:
  { 'provider_details.secondary_clinics': 1 }
  partialFilter exists

@CompoundIndex provider_office_ids:
  { 'provider_details.provider_office_ids': 1 }
  partialFilter exists

@CompoundIndex external_provider_id:
  { 'provider_details.external_provider_id': 1 }
  unique=true, sparse=true

@CompoundIndex primary_insurance:
  { 'provider_details.extra_info.primary_insurance': 1 }
  sparse=true

@CompoundIndex persona_basic_info:
  { 'last_name': 1, 'email': 1, 'dob': 1 }

@CompoundIndex lead_provider_activation:
  { 'provider_details.lead_provider_id': 1, 'provider_details.activation_date': 1 }
  partialFilter exists
```

| Field | Type | Notes |
|---|---|---|
| id | String | stored as `_id`; @Id; @JsonIgnore |
| isExpert | boolean | stored as `brook_member`; @Indexed; default false |
| isAdmin | boolean | stored as `is_admin`; default false |
| personaID | String | stored as `legacy_persona_id` |
| zoomUserId | String | stored as `zoom_user_id`; @Nullable; @Indexed(sparse=true); @JsonIgnore |
| oldPassword | String | stored as `password`; @Nullable; @JsonIgnore; @Deprecated field name reuse |
| password | String | stored as `password_2`; @JsonIgnore |
| hasRecentData | Boolean | stored as `has_recent_data` |
| unreadMessages | int | stored as `unreadMessages`; @JsonIgnore |
| lastExpertSent | Date | stored as `last_expert_sent`; @JsonIgnore |
| lastExpertRead | Date | stored as `last_expert_read`; @JsonIgnore |
| daysSinceRegistration | Integer | @Transient; @JsonIgnore |
| timeZoneOffset | Integer | stored as `time_zone_offset`; @Nullable |
| timeZone | String | stored as `time_zone`; @Nullable; @Indexed |
| useNewExpertChannel | Boolean | stored as `use_new_expert_channel`; @Nullable |
| termsAndConditionsAcceptances | List\<TermsAndConditionsAcceptance\> | stored as `terms_and_conditions` |
| is2faRequired | Boolean | stored as `is_2fa_required`; @Nullable |
| mfaEnabled | boolean | stored as `mfa_enabled` |
| lastLogin | Date | stored as `last_login`; @Nullable |
| firstLogin | Date | stored as `first_login`; @Nullable |
| isOutreach | Boolean | stored as `is_outreach`; default false |
| verificationDate | Date | stored as `verification_date`; @JsonIgnore |
| client | Client | stored as `client` |
| initialEmail | String | stored as `initial_email` |
| pubnubToken | String | stored as `pubnub_token` |
| brookBotChannel | String | stored as `chat_dialog_name` |
| partner | org.bson.Document | stored as `partner`; raw BSON doc |
| partnerCode | String | stored as `partner_code` |
| healthPartners | Partners | stored as `health_partners`; @AccessType(PROPERTY) |
| creationTime | Date | stored as `creation_time` |
| inviteOrigin | InviteOrigin | stored as `invite_origin` |
| motivations | List\<String\> | stored as `motivations`; @Nullable |
| medication | String | stored as `medication` |
| notes | List\<LegacyNote\> | stored as `notes` |
| shownTipsOfTheDay | List\<Integer\> | stored as `shown_tips_of_the_day`; @JsonIgnore |
| lastTipDate | Date | stored as `last_tip_date`; @JsonIgnore |
| services | Services | stored as `services` |
| preferences | PersonaPreferences | stored as `preferences` |
| goals | List\<org.bson.Document\> | stored as `goals`; raw BSON |
| hasSeenFirstInsight | Boolean | stored as `first_insight_completed`; default false |
| reminderPreferences | ReminderPreferences | stored as `reminder_preferences` |
| programs | List\<ProgramDetail\> | stored as `programs` |
| programEnrollments | List\<ProgramEnrollment\> | stored as `program_enrollments` |
| benefitInvestigations | Map\<String, BenefitInvestigationData\> | stored as `benefit_investigations` |
| outreach | Outreach | stored as `outreach` |
| onBehalfProviderOfficeId | String | @Transient |
| removedClinics | Set\<String\> | stored as `removed_clinics` |
| insurance | String | stored as `insurance` |
| treatPendingAsRpm | boolean | @Transient; default false |
| hubSpotContactId | String | stored as `hubspot_contact_id` |
| papPatientId | Long | stored as `pap_patient_id`; @Indexed |
| stageId | Long | stored as `stage_id` |
| previousStageId | Long | stored as `previous_stage_id` |
| stageUpdateTime | Date | stored as `stage_update_time` |
| resendInvite | Boolean | stored as `resend_invite` |
| doNotContact | Boolean | stored as `do_not_contact` |
| hubspotOwnerEmail | String | stored as `hubspot_owner_email` |
| hubspotOwnerId | Long | stored as `hubspot_owner_id` |
| impiloPatientId | String | stored as `impilo_patient_id` |
| diagnoses | List\<PersonaDiagnosis\> | stored as `diagnoses` |
| referralCode | ReferralCode | stored as `referral_code` |
| bluetoothDevices | List\<BTGlucometer\> | stored as `bluetooth_glucometers` |
| trial | Trial | stored as `trial` |
| registrationSource | Client.OperatingSystem | stored as `registration_source` |
| campaigns | List\<CampaignDetail\> | stored as `campaigns` |
| roles | Set\<UserRole\> | stored as `roles` |
| pendingRpmDetails | PendingRpmDetails | stored as `pending_rpm_details` |
| deleted | Boolean | stored as `deleted` |
| settings | Settings | stored as `settings` |
| appVersionString | String | stored as `appV`; getter only, no setter shown |

**Enums defined in Persona.java:**
- `NoEmailSource`: BULK, EMR, EMR_BULK

---

### ProgramEnrollment (embedded)
**File:** `src/main/java/ai/brook/data/persona/programenrollment/ProgramEnrollment.java`
**Collection:** embedded in `Persona.programEnrollments[]`

| Field | Type | Notes |
|---|---|---|
| enrollmentId | String | stored as `enrollment_id`; UUID |
| program | Program | stored as `program` |
| status | EnrollmentStatus | stored as `status` |
| enrollmentDate | Date | stored as `enrollment_date`; @Nullable |
| registeredDate | Date | stored as `registered_date`; @Nullable |
| activationDate | Date | stored as `activation_date`; @Nullable |
| disenrollmentDate | Date | stored as `disenrollment_date`; @Nullable; set before archiving |
| updatedAt | Date | stored as `updated_at`; @Nullable |
| providerOfficeId | String | stored as `provider_office_id`; @Nullable |
| mrn | String | stored as `mrn`; @Nullable |
| billable | Boolean | stored as `billable`; @Nullable; defaults true via getter |
| leadProviderId | String | stored as `lead_provider_id`; @Nullable |
| orderingProviderId | String | stored as `ordering_provider_id`; @Nullable |
| secondaryClinics | Set\<String\> | stored as `secondary_clinics`; @Nullable |
| referringClinic | String | stored as `referring_clinic`; @Nullable |
| emrOrderDate | Date | stored as `emr_order_date`; @Nullable |
| visitNumber | String | stored as `visit_number`; @Nullable |
| icd10Codes | Set\<String\> | stored as `icd10_codes`; @Nullable |
| investigationResult | InvestigationResult | stored as `investigation_result`; @Nullable |

---

### ProviderDetails (embedded)
**File:** `src/main/java/ai/brook/data/persona/ProviderDetails.java`
**Collection:** embedded in `Profile.providerDetails`

| Field | Type | Notes |
|---|---|---|
| mrn | String | stored as `mrn`; @Nullable |
| providerOfficeIds | List\<String\> | stored as `provider_office_ids`; @Nullable |
| externalProviderId | Long | stored as `external_provider_id` |
| leadProviderId | String | stored as `lead_provider_id` |
| orderingProviderId | String | stored as `ordering_provider_id` |
| officeName | String | stored as `office_name` |
| patientProviderOfficeId | String | stored as `patient_provider_office_id`; @Nullable |
| emailFlow | EmailType.RpmFlow | stored as `email_flow` |
| useServerEmails | Boolean | stored as `use_server_emails`; @Nullable |
| enrollmentDate | Date | stored as `enrollment_date`; @Nullable |
| registeredDate | Date | stored as `registered_date`; @Nullable; only set if currently null |
| manualActivationDate | Date | stored as `manual_activation_date`; @Nullable |
| activationDate | Date | stored as `activation_date`; @Nullable |
| deviceActivationDate | Date | stored as `device_activation_date`; @Nullable |
| newPatientIndicatorCleared | Boolean | stored as `new_patient_indicator_cleared`; @Nullable |
| isTransfer | Boolean | stored as `is_transfer`; @Nullable |
| transferDate | Date | stored as `transfer_date`; @Nullable |
| activityAlertThresholds | Map\<ThresholdType, ActivityThreshold\> | stored as `activity_alert_thresholds`; @Nullable |
| activityProtocols | Map\<ActivityType, BaseProtocol\> | stored as `activity_protocols`; @Nullable |
| latestActivities | Map\<ActivityType, Activity\> | stored as `latest_activities`; @JsonIgnore |
| activationSources | Map\<ActivityType, ActivationSource\> | stored as `activation_sources`; @Nullable |
| secondaryClinics | Set\<String\> | stored as `secondary_clinics`; @Nullable |
| billable | Boolean | stored as `billable`; @Nullable; defaults true via getter |
| npi | String | stored as `npi`; @Nullable; missing @Field — uses property name |
| nameAliases | List\<String\> | stored as `name_aliases`; @Nullable; EMR name matching (CAR-580) |
| provid | String | stored as `provid`; @Nullable; EMR id |
| orderingProvider | Boolean | stored as `ordering_provider`; @Nullable; defaults false |
| diagnosedCodes | Map\<ActivityType, Set\<String\>\> | stored as `diagnosed_codes`; @Nullable |
| extraInfo | ExtraInfo | stored as `extra_info`; @Nullable |
| benefitsInvestigation | BenefitsInvestigation | stored as `benefits_investigation`; @Nullable |
| referringClinic | String | stored as `referring_clinic`; @Nullable |
| visitNumber | String | stored as `visit_number`; @Nullable |
| acoParticipant | Boolean | stored as `aco_participant`; @Nullable |
| emrOrderDate | Date | stored as `emr_order_date`; @Nullable |
| inpatientSupport | Boolean | stored as `inpatient_support`; @Nullable; defaults false |
| inpatientBillingOffset | Integer | stored as `inpatient_billing_offset`; @Nullable |
| billingStartDate | Date | stored as `billing_start_date`; @Nullable |

---

### ProviderOffice
**File:** `src/main/java/ai/brook/api/rpm/provideroffice/model/ProviderOffice.java`
**Collection:** `provider_office`

| Field | Type | Notes |
|---|---|---|
| id | String | stored as `_id`; @Id |
| externalClinicId | Long | stored as `external_clinic_id`; @Indexed(unique=true, sparse=true) |
| name | String | stored as `name`; @NotBlank |
| preferredName | String | stored as `preferred_name`; @Nullable |
| isOrganization | Boolean | stored as `is_organization`; @Nullable |
| emrName | String | stored as `emr_name`; @Nullable; @Indexed |
| address | Address | stored as `address`; @Valid; @NotNull |
| timeZone | String | stored as `time_zone`; @IsTimeZone |
| phoneNumber | String | stored as `phone_number`; @NotBlank |
| phoneNumberType | PhoneNumberType | stored as `phone_number_type`; @Nullable |
| billableTypes | List\<ActivityType\> | stored as `billable_types`; @NotNull |
| emergencyPhoneNumber | String | stored as `emergency_phone_number`; @Nullable |
| emergencyPhoneNumberType | PhoneNumberType | stored as `emergency_phone_number_type`; @Nullable |
| faxNumber | String | stored as `fax_phone_number`; @Nullable |
| npi | String | stored as `npi`; @Nullable |
| activityAlertThresholds | Map\<ThresholdType, ActivityThreshold\> | stored as `activity_alert_thresholds`; @Nullable |
| activityProtocols | Map\<ActivityType, BaseProtocol\> | stored as `activity_protocols`; @Nullable |
| defaultDevices | Map\<ActivityType, List\<String\>\> | stored as `default_devices`; @Nullable |
| imageId | String | stored as `image_id`; @Nullable |
| imageUrl | String | stored as `image_url`; @Nullable |
| defaultLeadProviderId | String | stored as `default_lead_provider_id`; @Nullable |
| defaultPatientGroupId | String | stored as `default_patient_group_id`; @Nullable |
| isDemo | Boolean | stored as `is_demo`; @Nullable; defaults false |
| hubSpotEnabled | Boolean | stored as `hubspot_enabled`; @Nullable |
| papEnabled | Boolean | stored as `pap_enabled`; @Nullable |
| useServerEmails | Boolean | stored as `use_server_emails`; @Nullable; defaults false |
| bgQuestionnaire | Boolean | stored as `bg_questionnaire`; @Nullable |
| isAbTest | Boolean | stored as `is_ab_test`; @Nullable |
| brandForABTest | String | stored as `brand_for_ab_test`; @Nullable |
| totalLives | Integer | stored as `total_lives`; @Nullable; defaults 0 |
| recentReadingsThreshold | Integer | stored as `recent_readings_threshold`; @Nullable; defaults 4 |
| skipAlerts | Boolean | stored as `skip_alerts`; @Nullable |
| managedService | Boolean | stored as `managed_service`; @Nullable |
| invoiceGroups | Set\<InvoiceGroup\> | stored as `invoice_groups`; @Nullable |
| shippingOnRegistration | Boolean | stored as `shipping_on_registration`; @Nullable |
| usePartnerVerification | Boolean | stored as `use_partner_verification`; @Nullable |
| shippingTrigger | ShippingTrigger | stored as `shipping_trigger` |
| hideChannel | Boolean | stored as `hide_channel`; @Nullable |
| hidden | Boolean | stored as `hidden`; @Nullable |
| secondaryClinics | Set\<String\> | stored as `secondary_clinics`; @Nullable |
| reportConfiguration | ReportConfiguration | stored as `report_configuration` |
| carePlanExportConfiguration | CarePlanExportConfiguration | stored as `care_plan_export_configuration`; @Nullable |
| defaultEmailFlow | EmailType.RpmFlow | stored as `default_email_flow`; @Nullable |
| emrDetails | EmrDetails | stored as `emr_details`; @Nullable |
| emrActivityReportConfiguration | EmrActivityReportConfiguration | stored as `emr_activity_export_config`; @Nullable |
| acquisitionRules | AcquisitionRules | stored as `acquisition_rules`; @Nullable |
| alertFilterSchedule | AlertFilterConfiguration | stored as `alert_filter_schedule`; @Nullable |
| programParticipations | List\<ClinicProgramParticipation\> | stored as `program_participations`; @Nullable |
| acoParticipant | Boolean | stored as `aco_participant`; @Nullable |
| pcmCcmEnabled | Boolean | stored as `pcm_ccm_enabled`; @Nullable |
| rpmEnabled | Boolean | stored as `rpm_enabled`; @Nullable; defaults true |
| rpm2026CodesEnabled | Boolean | stored as `rpm_2026_codes_enabled`; @Nullable |
| monthlyVerificationEnabled | Boolean | stored as `monthly_verification_enabled`; @Nullable |
| monthlyVerificationPriority | Integer | stored as `monthly_verification_priority`; @Nullable |
| emrOrderRequiredForBilling | Boolean | stored as `emr_order_required_for_billing`; @Nullable |
| inpatientSupport | Boolean | stored as `inpatient_support`; @Nullable |
| inpatientBillingOffset | Integer | stored as `inpatient_billing_offset`; @Nullable |
| createdAt | Date | stored as `created_at`; @CreatedDate |
| updatedAt | Date | stored as `updated_at`; @Nullable; @LastModifiedDate |
| createdBy | String | stored as `created_by`; @CreatedBy |
| updatedBy | String | stored as `updated_by`; @Nullable; @LastModifiedBy |
| isSftpEnabled | Boolean | stored as `is_sftp_enabled` |
| isSftpCapable | Boolean | missing @Field — stored as `isSftpCapable` (property name) |
| organizationName | String | @Transient; @Nullable |
| defaultPsm | String | stored as `default_psm`; @Nullable |

**Enums:**
- `ShippingTrigger`: ENROLLMENT, REGISTRATION, FIRST_LOGIN
- `InvoiceGroup`: MANAGED_SERVICE, CATHOLIC_MEDICAL_PARTNERS, UMASS, ECMC, PMPM, INACTIVE, CGM, STURDY, GRIFFIN

---

### Appointment (collection)
**File:** `src/main/java/ai/brook/api/rpm/appointments/model/Appointment.java`
**Collection:** `appointments`

```
@CompoundIndex patient_provider_office:
  { 'persona_id': 1, 'provider_office_id': 1 }
```

| Field | Type | Notes |
|---|---|---|
| id | String | stored as `_id`; @Id |
| dueDate | Date | stored as `due_date`; @Deprecated |
| eventDate | Date | stored as `event_date`; @Nullable; getter falls back to dueDate |
| endDate | Date | stored as `end_date`; @Nullable |
| createdAt | Date | stored as `created_at`; @Nullable; @CreatedDate |
| createdBy | String | stored as `created_by`; @CreatedBy |
| personaId | String | stored as `persona_id`; @NotBlank |
| providerOfficeId | String | stored as `provider_office_id`; @NotBlank |
| type | AppointmentType | stored as `type`; @NotNull |
| source | AppointmentSource | stored as `source`; @Nullable |
| status | AppointmentStatus | stored as `appointment_status`; @Nullable; computed from eventDate if null |
| providerName | String | stored as `provider_name`; @Nullable |
| facilityName | String | stored as `facility_name`; @Nullable |
| notes | String | stored as `notes`; @Nullable |
| updatedBy | String | stored as `updated_by`; @Nullable |
| updatedAt | Date | stored as `updated_at`; @Nullable |
| deletedAt | Date | stored as `deleted_at`; @Nullable |

---

### Appointment (embedded outreach)
**File:** `src/main/java/ai/brook/api/users/model/outreach/Appointment.java`
**Collection:** embedded in `Persona.outreach`

| Field | Type | Notes |
|---|---|---|
| time | Date | stored as `time` |
| haveSpecificTime | Boolean | stored as `have_specific_time` |
| expertAssigned | String | stored as `expert_assigned`; @Nullable |
| expertFirstName | String | stored as `expert_first_name`; @Nullable |
| expertLastName | String | stored as `expert_last_name`; @Nullable |
| highPriority | Boolean | stored as `high_priority`; @Nullable |
| priorityDetails | PriorityDetails | stored as `priority_details`; @Nullable |

---

### PatientGroup
**File:** `src/main/java/ai/brook/api/rpm/patients/groups/model/PatientGroup.java`
**Collection:** `rpm.patient_group`

```
@CompoundIndex office_name:
  { provider_office_id: 1, name: 1 }

@CompoundIndex office_persona:
  { provider_office_id: 1, persona_ids: 1 }
```

| Field | Type | Notes |
|---|---|---|
| id | String | stored as `_id`; @Id |
| providerOfficeId | String | stored as `provider_office_id` |
| name | String | stored as `name` |
| personaIds | Set\<String\> | stored as `persona_ids`; @Indexed; @JsonIgnore |
| primaryMemberPersonaId | String | stored as `primary_member_persona_id` |
| secondaryMemberPersonaId | String | stored as `secondary_member_persona_id` |
| activePatientCount | Long | @Transient; used in `getSize()` |

---

### MonitoringTimeRaw
**File:** `src/main/java/ai/brook/api/rpm/billing/model/MonitoringTimeRaw.java`
**Collection:** `monitoring_time_raw`

```
@CompoundIndex persona_office_end:
  { 'persona_id': 1, 'provider_office_id': 1, 'end_time': -1 }

@CompoundIndex expert_start_end:
  { 'expert_id': 1, 'start_time': 1, 'end_time': 1 }

@CompoundIndex expert_end_start:
  { 'expert_id': 1, 'end_time': 1, 'start_time': 1 }
```

| Field | Type | Notes |
|---|---|---|
| id | String | stored as `_id`; @Id |
| personaId | String | stored as `persona_id`; @NotBlank |
| providerOfficeId | String | stored as `provider_office_id`; @NotBlank |
| expertId | String | stored as `expert_id`; @NotBlank |
| startTime | Date | stored as `start_time`; @NotNull |
| endTime | Date | stored as `end_time`; @NotNull |
| originalStartTime | Date | stored as `original_start_time`; @Nullable |
| originalEndTime | Date | stored as `original_end_time`; @Nullable |
| createdAt | Date | stored as `created_at`; @CreatedDate |
| updatedAt | Date | stored as `updated_at`; @Nullable; @LastModifiedDate |
| createdBy | String | stored as `created_by`; @CreatedBy |
| updatedBy | String | stored as `updated_by`; @Nullable; @LastModifiedBy |

---

### DeviceShippingDetails
**File:** `src/main/java/ai/brook/api/rpm/protocols/model/DeviceShippingDetails.java`
**Collection:** `device_shipping_details`

| Field | Type | Notes |
|---|---|---|
| id | String | stored as `_id`; @Id; @JsonIgnore |
| orderId | String | stored as `order_id`; @Indexed |
| trackerObjectId | String | stored as `tracker_object_id`; @Indexed |
| personaId | String | stored as `persona_id` |
| providerOfficeId | String | stored as `provider_office_id` |
| deviceNames | Set\<String\> | stored as `device_names` |
| trackingNumber | String | stored as `tracking_number` |
| prescriptionStatus | TrackerDetails.PrescriptionStatus | stored as `prescription_status` |
| shippingStatus | TrackerDetails.ShippingStatus | stored as `status` |
| createdAt | Instant | stored as `created_at` |
| lastUpdateAt | Instant | stored as `updated_at` |
| deviceOptions | List\<DeviceOptions\> | stored as `device_options` |

---

### ProviderDetailsHistory
**File:** `src/main/java/ai/brook/api/rpm/providerdetails/model/ProviderDetailsHistory.java`
**Collection:** `provider_details_history`

```
@CompoundIndex patient_type_provider_office:
  { 'patient_id': 1, 'event_type': 1, 'patient_provider_office_id': 1 }

@CompoundIndex office_type_created:
  { 'patient_provider_office_id': 1, 'event_type': 1, 'created_at': -1 }
```

| Field | Type | Notes |
|---|---|---|
| id | String | stored as `_id`; @Id |
| personaId | String | stored as `persona_id` |
| createdAt | Date | stored as `created_at`; @CreatedDate |
| createdBy | String | stored as `created_by`; @CreatedBy |
| eventType | ProviderDetailsEventType | stored as `event_type` |
| patientId | String | stored as `patient_id`; @NotBlank |
| patientProviderOfficeId | String | stored as `patient_provider_office_id`; @NotBlank |
| event | ProviderDetailsEvent | stored as `provider_details_event` |

**Enums:**
- `ProviderDetailsEventType`: REMOVE_RPM_PATIENT, REMOVE_SECONDARY_PATIENT, ADD_RPM_PATIENT, ADD_SECONDARY_PATIENT

---

### ConsentLogHistory (consent_log)
**File:** `src/main/java/ai/brook/api/consent/model/ConsentLogHistory.java`
**Collection:** `consent_log`

```
@CompoundIndex persona_provider_office_type_event:
  { 'persona_id': 1, 'provider_office_id': 1, 'type': 1, 'event': 1 }
```

| Field | Type | Notes |
|---|---|---|
| id | String | stored as `_id`; @Id |
| providerOfficeId | String | stored as `provider_office_id`; @NotBlank |
| personaId | String | stored as `persona_id`; @NotBlank |
| type | ConsentType | stored as `type`; @NotBlank |
| event | ConsentEventType | stored as `event`; @NotBlank |
| version | Number | stored as `version` |
| source | String | stored as `source` |
| evidence | String | stored as `evidence` |
| timestamp | Date | stored as `timestamp`; @NotBlank |
| createdAt | Date | stored as `created_at`; @CreatedDate |
| createdBy | String | stored as `created_by`; @CreatedBy |
| createdByPersonaId | String | stored as `created_by_persona_id` |
| originalCreatedBy | String | stored as `original_created_by` |
| originalCreatedByPersonaId | String | stored as `original_created_by_persona_id` |
| fileId | String | stored as `file_id` |

**Enums:**
- `ConsentEventType`: ADD, REMOVE

---

### CurrentConsent (current_consents)
**File:** `src/main/java/ai/brook/api/consent/model/CurrentConsent.java`
**Collection:** `current_consents`

```
@CompoundIndex persona_provider_office_type:
  { 'persona_id': 1, 'provider_office_id': 1, 'type': 1 }
```

| Field | Type | Notes |
|---|---|---|
| id | String | stored as `_id`; @Id |
| providerOfficeId | String | stored as `provider_office_id`; @NotBlank |
| personaId | String | stored as `persona_id`; @NotBlank |
| type | ConsentType | stored as `type`; @NotBlank |
| version | Number | stored as `version` |
| source | ConsentSource | stored as `source` |
| evidence | ConsentEvidence | stored as `evidence` |
| timestamp | Date | stored as `timestamp`; @NotBlank |
| createdAt | Date | stored as `created_at`; @CreatedDate |
| createdBy | String | stored as `created_by` |
| createdByPersonaId | String | stored as `created_by_persona_id` |
| fileId | String | stored as `file_id` |

---

### PatientCarePlans
**File:** `src/main/java/ai/brook/api/caremanagement/model/PatientCarePlans.java`
**Collection:** `patient_care_plans`

| Field | Type | Notes |
|---|---|---|
| id | String | stored as `_id`; @Id; @JsonIgnore |
| personaId | String | stored as `persona_id` |
| problemList | ProblemList | stored as `problem_list`; @Section |
| currentMedications | CurrentMedications | stored as `current_medications`; @Section |
| allergies | Allergies | stored as `allergies`; @Section |
| preventativeCare | PreventativeCare | stored as `preventative_care`; @Section |
| psychosocialAssessment | PsychosocialAssessment | stored as `psychosocial_assessment`; @Section |
| conditionSpecificCarePlans | List\<ConditionSpecificCarePlan\> | stored as `condition_specific_care_plans`; @Section |
| careTeams | CareTeams | stored as `care_teams`; @Section |
| updatedAt | Date | @Transient; always set to new Date() |

---

### CurrentMedications (embedded)
**File:** `src/main/java/ai/brook/api/caremanagement/model/CurrentMedications.java`
**Collection:** embedded in `PatientCarePlans.currentMedications`

Extends `Audit`.

| Field | Type | Notes |
|---|---|---|
| medications | List\<Medication\> | stored as `medications` |
| archived | boolean | stored as `archived`; default false |

**Nested Medication:**

| Field | Type | Notes |
|---|---|---|
| medication | String | stored as `medication` |
| dosage | String | stored as `dosage` |
| frequency | String | stored as `frequency` |
| comments | String | stored as `comments` |
| startDate | Date | stored as `start_date` |

---

### ChatRoom
**File:** `src/main/java/ai/brook/api/rooms/model/ChatRoom.java`
**Collection:** `chatRooms`

| Field | Type | Notes |
|---|---|---|
| id | String | stored as `_id`; @Id |
| userHasSentFirstMessage | boolean | stored as `user_has_sent_first_message`; @JsonIgnore; default false |
| roomId | String | stored as `room_id`; @Indexed(unique=true) |
| type | RoomType | stored as `type` |
| name | String | stored as `name` |
| subscribers | List\<Subscriber\> | stored as `subscribers`; @JsonIgnore |
| deletable | boolean | stored as `deletable` |
| hidden | Boolean | stored as `hidden`; @Nullable; @JsonIgnore |
| unreadMessages | int | stored as `unread_messages`; @JsonIgnore; @Indexed |
| oldestUnreadMessageAt | Date | stored as `oldest_unread_message_at`; @Nullable; @JsonIgnore |
| usePush | boolean | stored as `usePush` |
| group | ExpertGroup | stored as `group`; @Nullable |
| officeName | String | stored as `office_name`; @Nullable; @JsonIgnore |
| imageId | String | stored as `image_id`; @Nullable |
| expertStatus | RoomStatus | stored as `expert_status`; @Indexed; default CLOSED |
| interactions | List\<ExpertInteraction\> | stored as `interactions`; default empty list |
| expert | RoomExpert | stored as `assigned_to` |
| requestingPersona | PersonaDetails | @Transient; @JsonIgnore |
| statistics | ExpertStats | stored as `statistics`; @Nullable; @JsonIgnore |

**Enums:**
- `RoomStatus`: CLOSED, PENDING, ASSIGNED

---

### ExpertInteraction (embedded)
**File:** `src/main/java/ai/brook/api/rooms/model/ExpertInteraction.java`
**Collection:** embedded in `ChatRoom.interactions[]`

| Field | Type | Notes |
|---|---|---|
| pending | Date | stored as `pending`; set to `new Date()` in constructor |
| assigned | Date | stored as `assigned` |
| firstExpertResponse | Date | stored as `first_expert_response` |
| closed | Date | stored as `closed` |
| expertID | String | missing @Field — stored as `expertID` (property name) |
| category | String | stored as `category`; @Nullable |

---

## PAPI (py-pap — PostgreSQL)

### patient

| Field | Type | Notes |
|---|---|---|
| id | BIGINT GENERATED BY DEFAULT AS IDENTITY | NOT NULL; PK |
| clinic_id | TEXT | nullable; no FK constraint on DDL |
| csv_id | BIGINT | nullable; FK → csv_info(id) |
| enroll_owner | TEXT | nullable |
| enroll_status | TEXT | nullable |
| enroll_error_message | TEXT | nullable |
| enrollment_date | TIMESTAMPTZ | nullable |
| activation_date | TIMESTAMPTZ | nullable |
| persona_id | TEXT | nullable |
| communication_persona_id | TEXT | nullable |
| communication_notes | TEXT | nullable |
| communication_update_time | TIMESTAMPTZ | nullable |
| status | TEXT | nullable |
| low_tech | BOOLEAN | nullable |
| consent_authority_name | TEXT | nullable |
| consent_date | TIMESTAMPTZ | nullable |
| pcp_credentials | TEXT | nullable |
| active_insulin_rx | BOOL | nullable |
| active_metformin_rx | BOOL | nullable |
| address_city | TEXT | NOT NULL |
| address_line_1 | TEXT | NOT NULL |
| address_line_2 | TEXT | nullable |
| address_state | TEXT | NOT NULL |
| address_zipcode | TEXT | NOT NULL |
| bmi | NUMERIC(20,2) | nullable |
| chf | BOOL | nullable |
| chf_code | TEXT | nullable |
| ckd | BOOL | nullable |
| copd | BOOL | nullable |
| date_of_bmi | DATE | nullable |
| date_of_gfr | DATE | nullable |
| date_of_last_a1c | DATE | nullable |
| date_of_last_bp | DATE | nullable |
| dementia | BOOL | nullable |
| diabetes | BOOL | nullable |
| diabetes_code | TEXT | nullable |
| dob | DATE | NOT NULL |
| email_address | TEXT | nullable |
| endocrinologist | TEXT | nullable |
| ethnicity | TEXT | nullable |
| fasting_glucose_100 | BOOL | nullable |
| first_name | TEXT | NOT NULL |
| gender | TEXT | NOT NULL |
| glucometer | BOOL | nullable |
| height | NUMERIC(20,2) | nullable |
| hipaa_contacts | TEXT | nullable |
| home_phone | BOOL | nullable |
| home_phone_number | TEXT | nullable |
| hypertension | BOOL | nullable |
| hypertension_code | TEXT | nullable |
| insurance_group | TEXT | nullable |
| insurance_member_id | TEXT | nullable |
| insurance_name | TEXT | nullable |
| last_a1c | NUMERIC | nullable |
| a1c_info | TEXT | nullable |
| last_appointment | BOOL | nullable |
| last_appointment_dos | DATE | nullable |
| last_appointment_rendering_first_name | TEXT | nullable |
| last_appointment_rendering_last_name | TEXT | nullable |
| last_appointment_rendering_npi | TEXT | nullable |
| last_bnp_probnp | TEXT | nullable |
| last_bp_reading | TEXT | nullable |
| last_dbp | NUMERIC(20,2) | nullable |
| last_gfr | NUMERIC(20,2) | nullable |
| last_name | TEXT | NOT NULL |
| last_sbp | NUMERIC(20,2) | nullable |
| location | TEXT | nullable |
| mail | BOOL | nullable |
| mbi | TEXT | nullable |
| memberid | TEXT | nullable |
| mobile_phone | TEXT | nullable |
| mobile_text | BOOL | nullable |
| mobile_voice | TEXT | nullable |
| mrn | TEXT | nullable |
| next_scheduled_visit | TIMESTAMPTZ | nullable |
| next_scheduled_visit_provider | TEXT | nullable |
| npi | TEXT | nullable |
| obesity | BOOL | nullable |
| obesity_code | TEXT | nullable |
| pcp_name | TEXT | nullable |
| prediabetes | BOOL | nullable |
| provider_e_mail_address | TEXT | nullable |
| race | TEXT | nullable |
| secondary_ins | TEXT | nullable |
| secondary_ins_group | TEXT | nullable |
| secondary_ins_id | TEXT | nullable |
| send_via_email_portal | BOOL | nullable |
| weight | NUMERIC(20,2) | nullable |
| with_another_person | BOOL | nullable |
| mobile_call | BOOL | nullable |
| gfr_info | TEXT | nullable |
| next_scheduled_visit_type | TEXT | nullable |
| devices | JSONB | nullable |
| extras | JSONB | nullable |
| registered_date | TIMESTAMPTZ | nullable |
| referring_clinic | TEXT | nullable |
| register_token | TEXT | nullable |
| update_time | TIMESTAMPTZ | nullable; default CURRENT_TIMESTAMP |
| stage_id | BIGINT | nullable; default 999 |
| previous_stage_id | BIGINT | nullable; default 1000 |
| stage_update_time | TIMESTAMPTZ | nullable; default CURRENT_TIMESTAMP |
| benefits_investigation_request | TEXT | nullable |
| benefits_investigation_secondary_request | TEXT | nullable |
| benefits_investigation_result_message | TEXT | nullable |
| claim_rev_patient_id | INTEGER | nullable |
| benefits | JSONB | nullable |
| benefits_last_run | TIMESTAMPTZ | nullable; default CURRENT_TIMESTAMP |
| max_deductible | TEXT | nullable |
| deductible_remaining | TEXT | nullable |
| aco_participant | BOOLEAN | nullable |
| brain_health | BOOLEAN | nullable |
| pcm_ccm_consent_date | TIMESTAMPTZ | nullable |
| pcm_ccm_consent_authority_name | TEXT | nullable |
| apcm_consent_date | TIMESTAMPTZ | nullable |
| apcm_consent_authority_name | TEXT | nullable |
| resend_invite | BOOLEAN | nullable |
| emr_visit_number | TEXT | nullable |
| emr_order_date | TIMESTAMPTZ | nullable |
| provider_id | TEXT | nullable |
| do_not_contact | BOOLEAN | nullable; default FALSE |
| is_provider_referral | BOOLEAN | nullable; default FALSE |
| provider_referral_date | TIMESTAMPTZ | nullable |
| icd_10_codes | TEXT | nullable |
| program_outcomes | JSONB | nullable |
| next_scheduled_visit_permanent | TIMESTAMPTZ | nullable |
| last_appointment_permanent | BOOL | nullable |
| last_appointment_dos_permanent | DATE | nullable |
| investigation_outcomes | JSONB | nullable |
| risk_level | INTEGER | nullable |
| unique_user_key | TEXT | nullable; UNIQUE |
| bi_series_id | BIGINT | nullable |
| bi_status | TEXT | nullable |
| bi_updated_by | TEXT | nullable |
| bi_updated_at | TIMESTAMPTZ | nullable |

**Constraints / Indexes:**
- UNIQUE `(first_name, last_name, dob)` (inline)
- UNIQUE `unique_user_key` (inline)
- `idx_patient_bi_series_id ON patient (bi_series_id)`
- `idx_patient_bi_status ON patient (bi_status)`

---

### clinic

| Field | Type | Notes |
|---|---|---|
| id | TEXT | NOT NULL; PK; from MongoDB UUID (clinic_id) |
| ref_id | TEXT | nullable; null for root clinic |
| name | TEXT | nullable; location usually included |
| csv_schema_name | TEXT | nullable |
| status | TEXT | nullable; active or not |
| timezone | TEXT | nullable |
| create_time | TIMESTAMPTZ | nullable; default CURRENT_TIMESTAMP |
| update_time | TIMESTAMPTZ | nullable; default CURRENT_TIMESTAMP |

---

### clinic_acquisition_rules_snapshot

| Field | Type | Notes |
|---|---|---|
| id | BIGSERIAL | NOT NULL; PK |
| clinic_id | TEXT | NOT NULL |
| rules_hash | TEXT | NOT NULL |
| acquisition_rules | JSONB | NOT NULL |
| created_at | TIMESTAMPTZ | NOT NULL; default now() |
| updated_at | TIMESTAMPTZ | NOT NULL; default now() |

**Constraints / Indexes:**
- UNIQUE `(clinic_id, rules_hash)`
- `idx_clinic_acquisition_rules_snapshot_clinic_updated ON (clinic_id, updated_at DESC)`

---

### patient_rule_evaluation

| Field | Type | Notes |
|---|---|---|
| id | BIGSERIAL | NOT NULL; PK |
| patient_id | BIGINT | NOT NULL |
| clinic_id | TEXT | NOT NULL |
| rules_snapshot_id | BIGINT | NOT NULL; FK → clinic_acquisition_rules_snapshot(id) |
| trigger_source | TEXT | NOT NULL |
| triggered_by_field_changes | TEXT[] | nullable |
| pap_version | TEXT | nullable |
| patient_snapshot | JSONB | NOT NULL |
| rpm_eligible | BOOLEAN | NOT NULL |
| pcm_ccm_eligible | BOOLEAN | NOT NULL |
| apcm_eligible | BOOLEAN | NOT NULL |
| evaluated_at | TIMESTAMPTZ | NOT NULL; default now() |
| created_at | TIMESTAMPTZ | NOT NULL; default now() |
| updated_at | TIMESTAMPTZ | NOT NULL; default now() |

**Indexes:**
- `idx_patient_rule_evaluation_patient_evaluated ON (patient_id, evaluated_at DESC)`
- `idx_patient_rule_evaluation_clinic_evaluated ON (clinic_id, evaluated_at DESC)`
- `idx_patient_rule_evaluation_updated_at ON (updated_at DESC)`
- `idx_patient_rule_evaluation_clinic_rpm ON (clinic_id, rpm_eligible)`
- `idx_patient_rule_evaluation_clinic_pcm_ccm ON (clinic_id, pcm_ccm_eligible)`
- `idx_patient_rule_evaluation_clinic_apcm ON (clinic_id, apcm_eligible)`

**patient_rule_evaluation_results** (partitioned child table):

| Field | Type | Notes |
|---|---|---|
| id | BIGSERIAL | NOT NULL; part of composite PK (id, updated_at) |
| evaluation_id | BIGINT | NOT NULL; FK → patient_rule_evaluation(id) |
| program | TEXT | NOT NULL |
| rule_key | TEXT | NOT NULL |
| enabled | BOOLEAN | NOT NULL |
| passed | BOOLEAN | NOT NULL |
| failures | TEXT[] | nullable |
| created_at | TIMESTAMPTZ | NOT NULL; default now() |
| updated_at | TIMESTAMPTZ | NOT NULL; default now() |

- `PARTITION BY RANGE (updated_at)`; monthly partitions via helper functions
- UNIQUE `(evaluation_id, program, rule_key, updated_at)`
- `idx_pre_results_evaluation ON (evaluation_id)`
- `idx_pre_results_program_rule_passed ON (program, rule_key, passed)`
- `idx_pre_results_failures_gin USING GIN (failures)`

---

### csv_info

| Field | Type | Notes |
|---|---|---|
| id | BIGINT GENERATED BY DEFAULT AS IDENTITY | NOT NULL; PK |
| owner | TEXT | nullable |
| clinic_id | TEXT | NOT NULL; comment: FK constraint removed to enable auto-detection |
| create_time | TIMESTAMPTZ | nullable; default CURRENT_TIMESTAMP |
| filename | TEXT | nullable |
| csv_schema_name | TEXT | nullable |
| csv_header | JSONB | nullable |
| status | TEXT | nullable |
| update_time | TIMESTAMPTZ | nullable; default CURRENT_TIMESTAMP |
| extras | JSONB | nullable |

---

### note

| Field | Type | Notes |
|---|---|---|
| id | BIGINT GENERATED BY DEFAULT AS IDENTITY | NOT NULL; PK |
| author | TEXT | nullable |
| author_id | TEXT | NOT NULL; author's persona ID |
| patient_id | BIGINT | nullable; FK → patient(id) |
| create_time | TIMESTAMPTZ | nullable |
| update_time | TIMESTAMPTZ | nullable; default CURRENT_TIMESTAMP |
| type | TEXT | NOT NULL; CHECK IN ('interaction', 'follow_up', 'note') |
| assignee_id | TEXT | nullable; for follow_up type |
| callee | TEXT | nullable; for interaction type |
| resolution | BOOLEAN | nullable; default FALSE |
| call_result | TEXT | nullable |
| content | TEXT | nullable |
| due_date | DATE | nullable |
| reference_number | TEXT | nullable; for interaction type |
| deleted | BOOLEAN | nullable; default FALSE |
| resolution_type | TEXT | nullable |
| appointment_date | TIMESTAMPTZ | nullable |

---

### copay_history

| Field | Type | Notes |
|---|---|---|
| id | BIGINT GENERATED BY DEFAULT AS IDENTITY | NOT NULL; PK |
| patient_id | BIGINT | nullable; FK → patient(id) |
| insurance_group | TEXT | nullable |
| insurance_member_id | TEXT | nullable |
| insurance_name | TEXT | nullable |
| secondary_ins | TEXT | nullable |
| secondary_ins_group | TEXT | nullable |
| secondary_ins_id | TEXT | nullable |
| copay_amount_min | NUMERIC(20,2) | nullable |
| copay_amount_max | NUMERIC(20,2) | nullable |
| copay_notes | TEXT | nullable |
| update_time | TIMESTAMPTZ | nullable; default CURRENT_TIMESTAMP |
| program | TEXT | NOT NULL; CHECK IN ('rpm', 'pcm_ccm', 'apcm') |

---

### benefits_investigation_history

| Field | Type | Notes |
|---|---|---|
| id | BIGINT GENERATED BY DEFAULT AS IDENTITY | NOT NULL; PK |
| patient_id | BIGINT | nullable; no FK constraint |
| created_at | TIMESTAMPTZ | nullable; default CURRENT_TIMESTAMP |
| type | TEXT | nullable; CHECK IN ('primary', 'secondary') |
| message | TEXT | nullable |
| result | JSONB | nullable |
| claim_rev_patient_id | INTEGER | nullable |
| insurance_name | TEXT | nullable |
| insurance_member_id | TEXT | nullable |
| requested_at | TIMESTAMPTZ | nullable |
| acceleration_rule | INT4 | nullable |

**Indexes:**
- `idx_patient_id ON benefits_investigation_history (patient_id)`
- UNIQUE `idx_composite_key ON benefits_investigation_history (patient_id, type, created_at)`

---

### payer

| Field | Type | Notes |
|---|---|---|
| id | BIGINT GENERATED BY DEFAULT AS IDENTITY | NOT NULL; PK |
| payer_name | TEXT | NOT NULL |
| payer_number | TEXT | NOT NULL |

---

### payer_alias

| Field | Type | Notes |
|---|---|---|
| id | BIGINT GENERATED BY DEFAULT AS IDENTITY | NOT NULL; PK |
| payer_name | TEXT | NOT NULL |
| alias | TEXT | NOT NULL |

---

### payer_prefix

| Field | Type | Notes |
|---|---|---|
| id | BIGINT GENERATED BY DEFAULT AS IDENTITY | NOT NULL; PK |
| payer_name | TEXT | NOT NULL |
| payer_number | TEXT | NOT NULL |
| prefix | TEXT | NOT NULL |

---

### ICD-10 normalization (conditions.py / icd10.py)

**`normalize_icd10(raw: str) -> str`** — `brook/icd10.py`
- Splits on `~,;|/` and whitespace; uses first non-empty token
- Strips descriptive text; extracts leading code via regex `^([A-Z][0-9A-Z]{2,6})` after uppercasing and removing dots/hyphens
- Inserts dot after 3rd character if code length > 3
- Returns first valid code found, or `""` if none
- Raises `TypeError` if input is not a string

**ICD-10 code sets (`brook/icd10.py`):**
- `CHF_CODES`: I50.9, I50.22, I50.32, I50.42, 84114007, B410
- `DIABETES_CODES`: E10, E11, E13, 73211009, B280
- `HYPERTENSION_CODES`: I10, I11, I15, 38341003, B2801
- `OBESITY_CODES`: E66, E66.0, E66.1, E66.2, E66.8, 414916001, B515
- `NEUROP_CODES`: G60.9, G62.9, G63.2, G64, G90.0, G90.9, M79.2, M79.6, E08.42, B02.2
- `COPD_CODES`: J40, J44
- `CKD_CODES`: N18.1, N18.2, N18.3, N18.4, N18.5, N18.9, E0822, E0922, E1022, E1122, E1222, E1322, I12, I13

**`check_condition(code, codes, split=True) -> bool | None`** — `brook/conditions.py`
- Returns `None` if code is falsy
- Returns `False` if `code.lower()` in ("false", "f", "no", "n", "0", 0)
- Otherwise returns `True`; `codes` parameter is NOT used for matching; splitting logic commented out

**Condition → checker mapping (`CONDITIONS` dict):**
- `diabetes` → check_dm (DIABETES_CODES)
- `hypertension` → check_htn (HYPERTENSION_CODES)
- `chf` → check_chf (CHF_CODES)
- `obesity` → check_obesity (OBESITY_CODES)
- `copd` → check_copd (COPD_CODES)
- `ckd` → check_ckd (CKD_CODES)
- neuropathy — commented out of `CONDITIONS`

**Focused Primary Care code sets (`brook/conditions.py`):**
- `FOCUSED_CHF_CODES`: I501, I509, I5020, I5021, I5022, I5023, I5030, I5031, I5032, I5033, I5040, I5041, I5042, I5043, I5082, I5083, I5084, I5089
- `FOCUSED_DIABETES_CODES`: E088, E089, E119, E1122, E098, E099, E108, E109, E138, E139, E1100, E1300, E800, E900, E1069, E1169, E1269, E1369
- `FOCUSED_HYPERTENSION_CHF_CODES`: E110
- `FOCUSED_HYPERTENSION_CODES`: I10, I129, I110, I130, I150, I158, I159, I160, I119, I132, I1310, I151, I152, I161
- `FOCUSED_OBESITY_CODES`: E6601, E6609, E661, E662, E663, E668, E669
- `FOCUSED_COPD_CODES`: J40, J41, J42, J43, J44
- `FOCUSED_HYPERTENSION_CKD_CODES`: I12, I13 (treated as prefix)
- `FOCUSED_DIABETES_CKD_CODES`: E0822, E0922, E1022, E1122, E1222, E1322
- `FOCUSED_CKD_CODES`: N18 (treated as prefix)

---

## Billy (PostgreSQL)

### patients

| Field | Type | Notes |
|---|---|---|
| id | SERIAL | NOT NULL; PK |
| pap_id | TEXT | nullable; UNIQUE partial index (where not null) |
| persona_id | TEXT | nullable; UNIQUE partial index (where not null) |
| first_name | TEXT | NOT NULL |
| last_name | TEXT | NOT NULL |
| date_of_birth | DATE | NOT NULL |
| gender | TEXT | nullable |
| mrn | TEXT | nullable; added migration 20251106070533 |
| address | TEXT | nullable; added migration 20251106070533 |
| phone | TEXT | nullable; added migration 20251106070533 |
| email | TEXT | nullable; added migration 20251106070533 |
| created_at | TIMESTAMPTZ | NOT NULL; default CURRENT_TIMESTAMP |
| updated_at | TIMESTAMPTZ | NOT NULL; default CURRENT_TIMESTAMP |

---

### patient_insurances

| Field | Type | Notes |
|---|---|---|
| id | SERIAL | NOT NULL; PK |
| patient_id | INTEGER | NOT NULL; FK → patients(id) ON DELETE CASCADE |
| payer_name | TEXT | NOT NULL; renamed from insurance_provider_name (migration 20250702212809) |
| policy_number | TEXT | nullable |
| group_number | TEXT | nullable |
| member_id | TEXT | nullable |
| policy_holder_first_name | TEXT | nullable |
| policy_holder_last_name | TEXT | nullable |
| policy_holder_date_of_birth | DATE | nullable |
| priority_level | INTEGER | NOT NULL; CHECK (priority_level > 0) |
| is_active | BOOLEAN | NOT NULL; default TRUE |
| is_dependent | BOOLEAN | NOT NULL; default FALSE; added migration 20250701221308; replaces relationship_to_policy_holder |
| effective_month | TEXT | nullable; format "YYYY-MM"; NULL = standard investigation; added migration 20251107174633 |
| created_at | TIMESTAMPTZ | NOT NULL; default CURRENT_TIMESTAMP |
| updated_at | TIMESTAMPTZ | NOT NULL; default CURRENT_TIMESTAMP |

Removed columns (from original create): `relationship_to_policy_holder`, `effective_date`, `termination_date`

---

### payer_aliases (Billy)

| Field | Type | Notes |
|---|---|---|
| id | SERIAL | NOT NULL; PK |
| raw_payer_name | TEXT | NOT NULL; UNIQUE(raw_payer_name, clinic_npi) |
| clinic_npi | TEXT | NOT NULL |
| standard_payer_id | INTEGER | NOT NULL; FK → standard_payers(id) |
| created_at | TIMESTAMPTZ | NOT NULL; default CURRENT_TIMESTAMP |

---

### standard_payers

| Field | Type | Notes |
|---|---|---|
| id | SERIAL | NOT NULL; PK |
| name | TEXT | NOT NULL; UNIQUE |
| is_active | BOOLEAN | nullable; default true |
| created_at | TIMESTAMPTZ | NOT NULL; default CURRENT_TIMESTAMP |

`display_name` was created then dropped (migration 20250728224545).

---

### brokers

| Field | Type | Notes |
|---|---|---|
| id | SERIAL | NOT NULL; PK |
| name | TEXT | NOT NULL; UNIQUE |
| display_name | TEXT | NOT NULL |
| is_active | BOOLEAN | NOT NULL; default true |
| priority | INTEGER | NOT NULL; default 1; added migration 20250709000002 |
| created_at | TIMESTAMPTZ | NOT NULL; default CURRENT_TIMESTAMP |
| updated_at | TIMESTAMPTZ | NOT NULL; default CURRENT_TIMESTAMP |

---

### broker_payer_mappings

| Field | Type | Notes |
|---|---|---|
| id | SERIAL | NOT NULL; PK |
| standard_payer_id | INTEGER | NOT NULL; FK → standard_payers(id); UNIQUE(standard_payer_id, broker_id); refactored from payer_alias_id (migration 20250731130401) |
| broker_id | INTEGER | NOT NULL; FK → brokers(id) |
| broker_payer_id | TEXT | NOT NULL |
| created_at | TIMESTAMPTZ | NOT NULL; default CURRENT_TIMESTAMP |

---

### investigations

| Field | Type | Notes |
|---|---|---|
| id | INTEGER | NOT NULL; PK |
| patient_id | INTEGER | NOT NULL; FK → patients(id) ON DELETE CASCADE |
| assignee_id | INTEGER | nullable; FK → users(id) ON DELETE SET NULL; added migration 20250730060415 |
| clinic_npi | TEXT | NOT NULL |
| clinic_name | TEXT | NOT NULL |
| status | investigation_status | NOT NULL; PG enum |
| outputs | JSONB | nullable |
| attempt | INTEGER | NOT NULL; default 1; added migration 20250810180000 |
| series_id | INTEGER | NOT NULL; default 0; added migration 20250810180000; auto-populated by trigger |
| type | TEXT | NOT NULL; default 'standard'; CHECK IN ('standard','verification'); renamed from investigation_type migration 20251105214503 |
| verification_batch_id | INTEGER | nullable; FK → monthly_verification_batches(id); added migration 20251103220935 |
| created_at | TIMESTAMPTZ | NOT NULL; default CURRENT_TIMESTAMP |
| updated_at | TIMESTAMPTZ | NOT NULL; default CURRENT_TIMESTAMP |
| completed_at | TIMESTAMPTZ | nullable |

**investigation_status PostgreSQL enum values:**
queued, data_retrieved, under_review, completed, failed, cancelled, failed_update_insurance, verified_unchanged, verified_changed, requires_discovery, locked, coverage_undetermined, eligibility_blocked

**Kotlin Investigation.Status enum values** (superset — some may be app-layer only):
QUEUED, LOCKED, DATA_RETRIEVED, PARTIAL_DATA_RETRIEVED, UNDER_REVIEW, COMPLETED, FAILED, FAILED_UPDATE_INSURANCE, REDIRECT_RULE_REQUIRED, SERVICE_CODE_MAPPINGS_REQUIRED, CANCELLED, VERIFIED_UNCHANGED, VERIFIED_CHANGED, REQUIRES_DISCOVERY, COVERAGE_UNDETERMINED, ELIGIBILITY_BLOCKED

---

### monthly_verification_batches

| Field | Type | Notes |
|---|---|---|
| id | SERIAL | NOT NULL; PK |
| clinic_id | TEXT | NOT NULL |
| clinic_npi | TEXT | NOT NULL |
| clinic_name | TEXT | NOT NULL |
| clinic_address | TEXT | nullable; added migration 20251106070202 |
| verification_month | TEXT | NOT NULL |
| request_type | TEXT | NOT NULL |
| requested_by_persona_id | TEXT | nullable |
| requested_by | TEXT | nullable |
| priority | INT | NOT NULL |
| total_patients | INT | NOT NULL |
| patient_ids | TEXT[] | NOT NULL; changed from JSONB migration 20251103232358 |
| successful_count | INT | NOT NULL; default 0; added migration 20251103125327 |
| failed_count | INT | NOT NULL; default 0; added migration 20251103125327 |
| failure_details | JSONB | nullable; added migration 20251103125327 |
| created_at | TIMESTAMPTZ | NOT NULL; default CURRENT_TIMESTAMP |
| completed_at | TIMESTAMPTZ | nullable |
| status | TEXT | NOT NULL |

---

### users (Billy)

| Field | Type | Notes |
|---|---|---|
| id | SERIAL | NOT NULL; PK |
| google_user_id | TEXT | NOT NULL; UNIQUE |
| email | TEXT | NOT NULL; UNIQUE |
| first_name | TEXT | NOT NULL |
| last_name | TEXT | NOT NULL |
| profile_picture_url | TEXT | nullable |
| is_active | BOOLEAN | NOT NULL; default true |
| last_login_at | TIMESTAMPTZ | nullable |
| created_at | TIMESTAMPTZ | NOT NULL; default CURRENT_TIMESTAMP |
| updated_at | TIMESTAMPTZ | NOT NULL; default CURRENT_TIMESTAMP |

---

## ETL-service

### Change Stream Sources

| Collection | Java Constant | Transformer | Extractor |
|---|---|---|---|
| `persona` | `Fields.Mongo.Persona.COLLECTION_NAME` | `PersonaTransformer` | `PersonaExtractor` |
| `provider_office` | `Fields.Mongo.Clinic.COLLECTION_NAME` | `ClinicTransformer` | `ClinicExtractor` |
| `device_shipping_details` | `Fields.Mongo.DeviceShippingDetails.COLLECTION_NAME` | `DeviceShippingDetailsTransformer` | `DeviceShippingDetailsExtractor` |
| `consent_log` | `Fields.Mongo.ConsentLog.COLLECTION_NAME` | `ConsentLogTransformer` | `ConsentLogExtractor` |

---

### ConsentLogTransformer

**Fields consumed from change stream document:**

| Mongo Field | Constant | Used For |
|---|---|---|
| `persona_id` | `Fields.Mongo.ConsentLog.PERSONA_ID` | Identify patient; resolve `pap_patient_id` via persona lookup |
| `type` | `Fields.Mongo.ConsentLog.TYPE` | Consent type (rpm or pcm_ccm) |
| `event` | `Fields.Mongo.ConsentLog.EVENT` | Event type (add or remove); read from most-recent record |
| `timestamp` | `Fields.Mongo.ConsentLog.TIMESTAMP` | Consent date (epoch seconds) written to CIO |
| `created_by` | `Fields.Mongo.ConsentLog.CREATED_BY` | Consent authority name written to CIO |
| `created_at` | `Fields.Mongo.ConsentLog.CREATED_AT` | Removed-from-RPM date on remove events |

**CIO writes per event:**

| Event | Consent Type | CIO Workspace | CIO Fields Set |
|---|---|---|---|
| add | rpm | acquisition | Consent Date, Consent Authority Name, Removed From RPM Date (wiped to "") |
| add | rpm | providers | Removed From RPM Date (wiped to "") |
| add | pcm_ccm | acquisition | PCM CCM Consent Date, PCM CCM Consent Authority Name |
| remove | rpm | acquisition | Removed From RPM Date (epoch seconds) |
| remove | rpm | providers | Removed From RPM Date (epoch seconds) |
| remove | pcm_ccm | — | no-op, skipped |

**Idempotency:** On every change event, transformer calls `collectionLookupService.getMostRecentConsentEvent(personaId, consentType)` to fetch current most-recent record from `consent_log`. CIO payload is built from that record, not the change event. For `remove` events, `Thread.sleep(2000)` is inserted before lookup to allow a subsequent `add` (transfer pattern) ~500ms later to be written first.

---

### Customer.io Workspace Mapping

| Workspace Key | Usage |
|---|---|
| `acquisition` | Patients as PERSON objects; all consent, demographic, clinical fields |
| `providers` | Patients as OBJECT objects; object type from `customerio.providers-workspace.object-type-id.patient`; only RPM removal date |

**Config properties:**
- `customerio.api-key` / `customerio.site-id` — acquisition workspace
- `customerio.providers-workspace.api-key` / `customerio.providers-workspace.site-id` — providers workspace
- `customerio.providers-workspace.object-type-id.patient` — object type ID for patients in providers workspace

---

### resume_token collection

**Java model:** `ResumeToken.java` with `@Document("resume_token")`

| Field | Constant | Type | Notes |
|---|---|---|---|
| collection_name | `Fields.Misc.ResumeToken.COLLECTION_NAME` | String | Which Mongo collection this token belongs to |
| resume_token | `Fields.Misc.ResumeToken.RESUME_TOKEN` | String | JSON-serialized BSON resume token |
| created_at | `Fields.Misc.ResumeToken.CREATED_AT` | Date | When the token was last persisted |

- Read on startup: checks in-memory `ConcurrentHashMap` first, then queries `resume_token` collection
- Written after each successfully processed document via `mongoTemplate.upsert()` keyed on `collection_name`
- On error 286 (`ChangeStreamHistoryLost`) or label `NonResumableChangeStreamError`: discards token, starts fresh change stream

---

### All @Document collections

| Java Class | @Document Collection |
|---|---|
| `ResumeToken` | `resume_token` |

`persona`, `provider_office`, `device_shipping_details`, `consent_log` are referenced as raw string constants in `Fields.java` via `MongoTemplate.getCollection()` — no Spring Data `@Document`-annotated model classes for these.

---

## report-service

### BillingResultDetailed entity

**File:** `src/main/java/ai/brook/report/entity/BillingResult.java`
**Annotation:** `@Entity @Table(name = "billing_result_detailed", schema = "dbt_gold_billing")`

| Field | Type | Notes |
|---|---|---|
| id | String | @Id |
| userId | String | |
| clinicId | String | |
| billingClinicId | String | |
| firstName | String | |
| lastName | String | |
| dob | Date | |
| mrn | String | |
| conditions | String | |
| isBillable | Boolean | |
| clinicName | String | |
| billingClinicName | String | |
| providerFirstName | String | |
| providerLastName | String | |
| startTime | Date | |
| endTime | Date | |
| type | String | |
| periodNumber | Integer | |
| periodStart | Date | |
| periodEnd | Date | |
| achieved | Boolean | |
| activityData | String | JSON |
| setupDevices | String | JSON |
| deviceStatus | String | |
| monitoringCodesAchieved | String | JSON |
| monitoringData | String | JSON |
| interactionData | String | JSON |
| carePlanConditionData | String | JSON |
| carePlanReviewData | String | JSON |
| carePlanUpdateData | String | JSON |
| monitoringSeconds | Long | |
| interactionSeconds | Long | |
| mergedMonitoringSeconds | Long | |
| consentStart | Date | no explicit @Column; relies on Spring implicit naming strategy camelCase → snake_case (`consent_start`) |
| timeZone | String | |
| firstEducationNoteTs | Date | |
| rpm2026CodesEnabled | Boolean | `@Column(name = "rpm_2026_codes_enabled")` — explicit override |

---

### All @Entity / @Document / @Table inventory

| Class | Table Name | Schema |
|---|---|---|
| BillingResult | billing_result_detailed | dbt_gold_billing |
| DeviceCountColumn | device_count_column | dbt_gold_billing |
| InvoiceReport | invoice_report | dbt_gold_billing |
| InvoiceReportDevice | invoice_report_device | dbt_gold_billing |
| JobStatus | job_status | dbt_gold_billing |

All entities use JPA `@Entity`. No `@Document` or `@MappedEntity` annotations found. report-service is **read-only** with respect to `consent_log` and `current_consents` — no tables by those names exist as entities.

---

## data-platform (dbt)

### Consent Models

**`billing/patient/patient_consent.sql`**
- Sources: `billing_mongodb_public.persona_consent_log`; upstream ref: `{{ ref('patient') }}`
- Output columns: `user_id`, `clinic_id`, `rpm_consent_start`, `pcm_ccm_consent_start`

```sql
-- earliest_add CTE: MIN(start_time) WHERE event='add', grouped by persona_id/provider_office_id/type
-- latest_event CTE: last event per (persona_id, provider_office_id, type) ORDER BY created_at DESC

-- Included if: last event = 'add'
--           OR last event = 'remove' AND created_at >= var('start_time')
-- Excluded if: last event = 'remove' AND created_at < var('start_time')

rpm_consent_start      = MIN(ea.consent_start) WHERE type='rpm'     AND (le.event='add' OR le.created_at >= start_time)
pcm_ccm_consent_start  = MIN(ea.consent_start) WHERE type='pcm_ccm' AND (le.event='add' OR le.created_at >= start_time)
```

- Migrated from `persona_current_consents` (full-load) to `persona_consent_log` (append-only, last-event-wins) per fix DNA-642

**`staging/rpm/stg_persona_consent.sql`**
- Source: `brook_rpm_core.persona_consent_log`
- Output: `_ID`, `PROVIDER_OFFICE_ID`, `PERSONA_ID`, `TYPE`, `EVENT`, `VERSION`, `SOURCE`, `EVIDENCE`, `START_TIME`, `CREATED_AT`, `CREATED_BY`, `CREATED_BY_PERSONA_ID`, `FILE_ID`
- Filters `event = 'add'` only; deduplicates via `ROW_NUMBER() OVER (PARTITION BY persona_id, type, provider_office_id ORDER BY start_time DESC, created_at DESC) = 1`

**`intermediate/growth/int_persona_consent_removed.sql`**
- Sources: `mongodb_prod.public.persona_consent_log`, `mongodb_prod.public.persona_current_consents`; refs: `stg_provider_office`, `stg_persona_consent`, `prod_gold.public.cio_clinics`
- Output: `persona_id`, `disenrolled_clinic_id`, `disenrolled_clinic_name`, `clinic_status`, `clinic_type`, `rpm_consent_disenrolled`, `rpm_consent_start_enrolled`, `rpm_consent_authority_disenrolled`, `rpm_consent_authority_enrolled`, `pcm_ccm_consent_disenrolled`, `pcm_ccm_consent_start_enrolled`, `pcm_ccm_consent_authority_disenrolled`, `pcm_ccm_consent_authority_enrolled`
- Takes latest `remove` event per patient/type; excludes rows where `current_consents` still shows program enabled at that office

---

### billing_result_detailed

**`billing/cpt_code/billing_result_detailed.sql`**
- Materialization: incremental (`delete+insert`), schema `gold_billing`
- Upstream refs: `billing_result_stage_3`, `patient`, `clinic`, `provider`, `patient_education_note`
- Source tables: `billing_mongodb_public.provider_office_billing_mapping`

**`billing_result_stage_2.sql` — consent_start assignment:**
```sql
CASE
  WHEN br.type IN (rpm_codes)     THEN pc.rpm_consent_start
  WHEN br.type IN (pcm_ccm_codes) THEN pc.pcm_ccm_consent_start
  ELSE var('start_time')
END AS consent_start
```

**`billing_result_stage_3.sql` — consent eligibility gate:**
```sql
IFF(br.achieved = TRUE AND br.consent_start < br.period_end, TRUE, FALSE) AS achieved
```

---

### ICD-10 Models

**`intermediate/growth/int_icd10_condition_mapping_cleaned.sql`**
- Source: `SIGMA_WRITE_DB.SIGMA_MATERIALIZATIONS.icd_10_condition_mapping` (external Sigma table)
- Output: `icd_10_code`, `condition`
- Flattens comma-separated ICD codes per condition row; deduplicates with `SELECT DISTINCT`

**`intermediate/growth/int_patient_icd10_conditions.sql`**
- Sources: `papi_prod.public.patient`, `papi_prod.public.patient_archive`
- Upstream ref: `{{ ref('int_icd10_condition_mapping_cleaned') }}`
- Output: `lead_id_pap`, `icd_10_codes`, `condition_array_mapped`
- ICD codes stored as tilde-separated strings in `papi.public.patient.icd_10_codes`
- `LATERAL FLATTEN(SPLIT(icd_10_codes, '~'))` splits into individual codes
- Aggregates matched conditions into `ARRAY_AGG(DISTINCT condition)` per patient
- Deduplicates active/archive via `ROW_NUMBER() OVER (PARTITION BY lead_id_pap ORDER BY update_time DESC) = 1`

---

### Model Catalog Summary

| Attribute | Value |
|---|---|
| dbt project name | brook_transform |
| profile | data_management |
| Total SQL models (management) | 271 |
| Total SQL models (analytics) | 2 |
| management/models/ subdirectories | adhoc_reports, billing, carebot, intermediate, marts, population_health, rpm, staging |

`diagnosed_codes` — NOT FOUND in `Brookai/data-platform`. No models contain this field name.

---

### dbt_project.yml schedules/tags

NOT FOUND — sweep results do not include dbt_project.yml schedule or tag configuration.

---

## Cross-cutting

### ICD-10 Location Inventory

| # | Location | Status |
|---|---|---|
| 1 | `brook-backend` — `PersonaDiagnosis.icd10Code` (`persona.diagnoses[].icd10_code`) | CONFIRMED |
| 2 | `brook-backend` — `ProgramEnrollment.icd10Codes` (`persona.program_enrollments[].icd10_codes`) | CONFIRMED |
| 3 | `brook-backend` — `ProviderDetails.diagnosedCodes` (`persona.provider_details.diagnosed_codes`) | CONFIRMED |
| 4 | `py-pap` — `patient.icd_10_codes` (TEXT; tilde-separated) | CONFIRMED |
| 5 | `py-pap` — `brook/icd10.py` and `brook/conditions.py` (normalization + code sets) | CONFIRMED |
| 6 | `data-platform` — `int_icd10_condition_mapping_cleaned.sql` (Sigma source) | CONFIRMED |
| 7 | `data-platform` — `int_patient_icd10_conditions.sql` (reads papi `icd_10_codes`, tilde-splits) | CONFIRMED |

---

### Deduplication Inventory

- `patient` table: UNIQUE `(first_name, last_name, dob)` and UNIQUE `unique_user_key`
- `clinic_acquisition_rules_snapshot`: UNIQUE `(clinic_id, rules_hash)`
- `patient_rule_evaluation_results`: UNIQUE `(evaluation_id, program, rule_key, updated_at)`
- `benefits_investigation_history`: UNIQUE `(patient_id, type, created_at)`
- Billy `patients`: UNIQUE partial on `pap_id` (where not null), UNIQUE partial on `persona_id` (where not null)
- Billy `payer_aliases`: UNIQUE `(raw_payer_name, clinic_npi)`
- Billy `broker_payer_mappings`: UNIQUE `(standard_payer_id, broker_id)`
- Billy `standard_payers.name`: UNIQUE
- Billy `brokers.name`: UNIQUE
- `persona` (Mongo): compound index `persona_basic_info { last_name, email, dob }`; compound unique `persona_patient_office`; unique sparse `external_provider_id`
- `provider_office` (Mongo): unique sparse `external_clinic_id`
- `stg_persona_consent.sql`: deduplicates by `ROW_NUMBER() OVER (PARTITION BY persona_id, type, provider_office_id ORDER BY start_time DESC, created_at DESC) = 1`
- `int_patient_icd10_conditions.sql`: deduplicates active/archive by `ROW_NUMBER() OVER (PARTITION BY lead_id_pap ORDER BY update_time DESC) = 1`

---

### Consent Pipeline (steps 1–6)

| Step | Description | Status |
|---|---|---|
| 1 | Brook backend writes consent event to `consent_log` (MongoDB) as `ConsentLogHistory` with `event = ADD\|REMOVE` | CONFIRMED |
| 2 | Brook backend maintains `current_consents` (MongoDB) as `CurrentConsent` — current active state per patient/office/type | CONFIRMED |
| 3 | ETL-service watches `consent_log` change stream via `ConsentLogTransformer`; on every event fetches most-recent record for idempotency; writes RPM/PCM consent fields to Customer.io acquisition and providers workspaces | CONFIRMED |
| 4 | ETL-service (PersonaTransformer) syncs `persona` changes to downstream systems (PAP `pap_patient_id` cross-reference maintained) | CONFIRMED |
| 5 | dbt `patient_consent.sql` reads `persona_consent_log` (Snowflake ETL copy of `consent_log`) to compute `rpm_consent_start` / `pcm_ccm_consent_start` per billing period; migrated from `current_consents` per DNA-642 | CONFIRMED |
| 6 | dbt `billing_result_stage_2/3.sql` applies `consent_start` to billing CPT code rows; code is only marked achieved if `consent_start < period_end` | CONFIRMED |

---

### RegisterService PAP→Persona Field Mapping

NOT FOUND. `RegisterService.java` and `RegisterEngine.java` returned 404 via `gh api`. `gh search code --repo Brookai/brook-backend "RegisterService"` returned empty result. Field mapping between PAP patient and Persona on registration is not captured in sweep results.

---

### Missing @Field Annotation Inventory

| Class | Field | Java Name | Actual Stored Name | Impact |
|---|---|---|---|---|
| `ProviderDetails` | npi | `npi` | `npi` (property name) | Low — property name matches intended key |
| `ProviderOffice` | isSftpCapable | `isSftpCapable` | `isSftpCapable` (camelCase) | Medium — inconsistent with snake_case convention used elsewhere |
| `ExpertInteraction` | expertID | `expertID` | `expertID` (camelCase) | Medium — inconsistent with snake_case convention |

---

### PAI-184 Status (all repos)

| Repo | Status |
|---|---|
| brook-backend | MERGED — PR #1611 merged 2026-05-20; adds canonical `persona.diagnoses[]` store (`PersonaDiagnosis` class); branch `feat/PAI-184-icd10-patient-profile` |
| py-pap | NOT FOUND — no PAI-184 branches or commits found in this repo |
| Billy | NOT FOUND — not searched in sweep results |
| ETL-service | NOT FOUND — not searched in sweep results |
| report-service | NOT FOUND — not searched in sweep results |
| data-platform | NOT FOUND — not searched in sweep results |

---

## Open Questions

- [brook-backend] RegisterService/RegisterEngine not found via search or direct path — where does PAP→Persona field mapping occur on patient registration? What fields are written from `patient` to `persona` at enrollment time?
- [brook-backend] `ConsentType` enum values not captured — what are the full set of values (rpm, pcm_ccm, apcm, others)?
- [brook-backend] `PersonaDiagnosis.DiagnosisSource` enum values not captured from sweep.
- [py-pap] PAI-184 not present — is `icd_10_codes` (tilde-separated TEXT) the interim store until the `persona.diagnoses[]` canonical store is fully adopted, or does PAP maintain its own independent ICD-10 record indefinitely?
- [py-pap] `patient.icd_10_codes` is plain TEXT with tilde delimiter — no normalization applied at write time; `normalize_icd10()` is only called on ingest. Is there a backfill for existing malformed values?
- [py-pap] `check_condition()` in `conditions.py` ignores the `codes` parameter entirely (matching logic commented out) — is this intentional or a regression?
- [Billy] `PARTIAL_DATA_RETRIEVED`, `REDIRECT_RULE_REQUIRED`, `SERVICE_CODE_MAPPINGS_REQUIRED` exist in Kotlin `Investigation.Status` enum but no explicit `ALTER TYPE ... ADD VALUE` migration was found — confirm these are in the PG enum or document that they are app-layer only.
- [Billy] `eligibility_blocks.occurrence_count` was dropped in migration 20260501004736 but column still appears in the schema above — confirm removal is complete in production.
- [ETL-service] Does `PersonaTransformer` sync `persona.diagnoses[]` (PAI-184 field) to any downstream system, or is that propagation not yet implemented?
- [ETL-service] `apcm` consent type not handled in `ConsentLogTransformer` (only `rpm` and `pcm_ccm` branches exist) — is APCM consent propagation to CIO out of scope or a gap?
- [data-platform] `dbt_project.yml` schedule/tag configuration not captured in sweep — what is the run cadence for billing models?
- [data-platform] `diagnosed_codes` (from `ProviderDetails`) has no corresponding dbt model — is this field used downstream anywhere outside Mongo?
- [report-service] All five `dbt_gold_billing` JPA entities are read-only from the service perspective — confirm no other service writes to `billing_result_detailed` outside dbt.
