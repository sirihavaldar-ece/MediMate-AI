import * as React from "react";
import { useCallback, useEffect, useState } from "react";
import VoiceAssistant from "../components/VoiceAssistant.jsx";
import {
  askForHelp,
  confirmDose,
  createMedication,
  deleteMedication,
  deactivateMedication,
  fetchCaregiverDashboard,
  fetchPatientDashboard,
  fetchVoiceCallHistory,
  fetchVoiceConsent,
  linkCaregiverPatient,
  remindAgain,
  saveVoiceConsent,
  unlinkCaregiver,
  updateMedication,
} from "../api/client.js";

function formatTime(value, timezone) {
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
    timeZone: timezone,
  }).format(new Date(value));
}

function currentDateInTimezone(timezone) {
  const parts = new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    month: "2-digit",
    timeZone: timezone,
    year: "numeric",
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T12:00:00Z`));
}

function formatDateInTimezone(value, timezone) {
  return new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    timeZone: timezone,
  }).format(new Date(value));
}

function DoseCard({ dose, onAction, busy }) {
  const actionable = ["upcoming", "due", "missed_unconfirmed"].includes(dose.status);
  return (
    <article className={`dose-card dose-${dose.status}`}>
      <div className="dose-time">
        {formatTime(dose.scheduled_at, dose.timezone)}
      </div>
      <div className="dose-details">
        <h3>{dose.medication_name}</h3>
        {dose.instructions && <p>{dose.instructions}</p>}
        <span className={`status-pill status-${dose.status}`}>
          {dose.status.replaceAll("_", " ")}
        </span>
      </div>
      {actionable && (
        <div className="dose-actions">
          <button
            className="primary-button"
            disabled={busy}
            onClick={() => onAction(dose.id, "confirm")}
            type="button"
          >
            I have taken it
          </button>
          <button
            className="secondary-button"
            disabled={busy}
            onClick={() => onAction(dose.id, "remind")}
            type="button"
          >
            Remind me again
          </button>
          <button
            className="text-button"
            disabled={busy}
            onClick={() => onAction(dose.id, "help")}
            type="button"
          >
            Need help
          </button>
        </div>
      )}
    </article>
  );
}

function MedicationForm({ patientId, timezone, onCreated, medication, onCancel }) {
  const [name, setName] = useState(medication?.name ?? "");
  const [instructions, setInstructions] = useState(medication?.instructions ?? "");
  const [scheduleTimes, setScheduleTimes] = useState(
    medication?.schedule_times?.join(", ") ?? "08:00",
  );
  const [startDate, setStartDate] = useState(
    medication?.start_date ?? currentDateInTimezone(timezone),
  );
  const [endDate, setEndDate] = useState(medication?.end_date ?? "");
  const [repeatInterval, setRepeatInterval] = useState(
    medication?.repeat_interval_minutes ?? 30,
  );
  const [escalationDelay, setEscalationDelay] = useState(
    medication?.escalation_delay_minutes ?? 120,
  );
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setError("");
    setSaving(true);
    try {
      const values = {
        ...(patientId ? { patient_id: patientId } : {}),
        name,
        instructions,
        schedule_times: scheduleTimes.split(",").map((value) => value.trim()).filter(Boolean),
        start_date: startDate,
        end_date: endDate || null,
        timezone,
        repeat_interval_minutes: Number(repeatInterval),
        escalation_delay_minutes: Number(escalationDelay),
      };
      if (medication) {
        await updateMedication(medication.id, values);
      } else {
        await createMedication(values);
      }
      await onCreated();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Could not save schedule.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="medication-form" onSubmit={submit}>
      <h3>{medication ? `Edit ${medication.name}` : "Add prescribed schedule"}</h3>
      <p className="field-hint">Enter only the medication and schedule from the patient’s existing instructions.</p>
      <p className="field-hint">Use 24-hour HH:MM times. Separate multiple daily times with commas.</p>
      <label>
        Medication name
        <input maxLength={120} onChange={(event) => setName(event.target.value)} required value={name} />
      </label>
      <label>
        Prescribed instructions (optional)
        <textarea
          maxLength={1000}
          onChange={(event) => setInstructions(event.target.value)}
          rows={2}
          value={instructions}
        />
      </label>
      <div className="form-row">
        <label>
          Reminder times
          <input
            onChange={(event) => setScheduleTimes(event.target.value)}
            placeholder="08:00, 20:00"
            required
            value={scheduleTimes}
          />
        </label>
        <label>
          Time zone
          <input readOnly value={timezone} />
        </label>
      </div>
      <div className="form-row">
        <label>
          Repeat reminder (minutes)
          <input
            max="1440"
            min="5"
            onChange={(event) => setRepeatInterval(event.target.value)}
            required
            type="number"
            value={repeatInterval}
          />
        </label>
        <label>
          Caregiver escalation (minutes)
          <input
            max="10080"
            min="10"
            onChange={(event) => setEscalationDelay(event.target.value)}
            required
            type="number"
            value={escalationDelay}
          />
        </label>
      </div>
      <div className="form-row">
        <label>
          Start date
          <input
            onChange={(event) => setStartDate(event.target.value)}
            required
            type="date"
            value={startDate}
          />
        </label>
        <label>
          End date (optional)
          <input
            min={startDate}
            onChange={(event) => setEndDate(event.target.value)}
            type="date"
            value={endDate}
          />
        </label>
      </div>
      {error && <p className="error-message" role="alert">{error}</p>}
      <button className="primary-button" disabled={saving} type="submit">
        {saving ? "Saving…" : medication ? "Save changes" : "Save schedule"}
      </button>
      {onCancel && (
        <button className="secondary-button" onClick={onCancel} type="button">
          Cancel editing
        </button>
      )}
    </form>
  );
}

function PatientDashboard({ data, refresh }) {
  const [busyDoseId, setBusyDoseId] = useState(null);
  const [editingMedicationId, setEditingMedicationId] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [voiceConsent, setVoiceConsent] = useState(null);
  const [voicePhone, setVoicePhone] = useState("");
  const [voiceMessage, setVoiceMessage] = useState("");
  const [voiceSaving, setVoiceSaving] = useState(false);
  const [voiceCallHistory, setVoiceCallHistory] = useState([]);
  const dueDose = data.doses.find((dose) => ["due", "missed_unconfirmed"].includes(dose.status));
  const lastConfirmed = data.history
    .filter((dose) => dose.status === "confirmed_by_patient")
    .at(-1);

  useEffect(() => {
    fetchVoiceConsent()
      .then((value) => {
        setVoiceConsent(value);
        setVoicePhone(value.phone_number ?? "");
      })
      .catch((voiceError) => {
        setError(voiceError instanceof Error ? voiceError.message : "Could not load voice-call consent.");
      });
    fetchVoiceCallHistory()
      .then(setVoiceCallHistory)
      .catch((voiceError) => {
        setError(voiceError instanceof Error ? voiceError.message : "Could not load call history.");
      });
  }, []);

  async function saveVoiceSettings(enabled) {
    setVoiceSaving(true);
    setError("");
    setVoiceMessage("");
    try {
      const value = await saveVoiceConsent({
        phone_number: voicePhone,
        enabled,
      });
      setVoiceConsent(value);
      setVoicePhone(value.phone_number ?? "");
      setVoiceCallHistory(await fetchVoiceCallHistory());
      setVoiceMessage(
        enabled
          ? value.provider_configured
            ? "Consent saved. Eligible future escalations may trigger one automated call and a retry."
            : "Consent saved, but calls are simulated because Twilio is not configured."
          : "Automated call consent was withdrawn and the saved number was removed.",
      );
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Could not save call preferences.");
    } finally {
      setVoiceSaving(false);
    }
  }

  async function handleDoseAction(id, action) {
    setBusyDoseId(id);
    setError("");
    setMessage("");
    try {
      const result =
        action === "confirm"
          ? await confirmDose(id)
          : action === "remind"
            ? await remindAgain(id)
            : await askForHelp(id);
      setMessage(
        action === "confirm"
          ? "Dose confirmed. The top panel is waiting for your next scheduled dose."
          : result.message,
      );
      if (action === "confirm" && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(new SpeechSynthesisUtterance(
          "Thank you. Have a good day.",
        ));
      }
      await refresh();
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "That action could not be completed.");
    } finally {
      setBusyDoseId(null);
    }
  }

  return (
    <section className="dashboard" aria-labelledby="dashboard-title">
      <div className="dashboard-heading">
        <div>
          <p className="eyebrow">Patient dashboard</p>
          <h1 id="dashboard-title">Hello, {data.user.name}.</h1>
          <p className="muted-copy">{formatDate(data.today)} · {data.user.timezone}</p>
        </div>
      </div>
      {message && <p className="success-message" role="status">{message}</p>}
      {error && <p className="error-message" role="alert">{error}</p>}
      <section className="dose-focus" aria-label="Current medication confirmation">
        {dueDose ? (
          <>
            <button
              aria-label={`Confirm you have taken ${dueDose.medication_name}`}
              className="dose-confirm-button dose-confirm-red"
              disabled={busyDoseId === dueDose.id}
              onClick={() => handleDoseAction(dueDose.id, "confirm")}
              type="button"
            >
              <span>{busyDoseId === dueDose.id ? "SAVING…" : "I HAVE TAKEN"}</span>
              <strong>{dueDose.medication_name}</strong>
            </button>
            <h2>{dueDose.medication_name}</h2>
            <p>{dueDose.instructions || `Scheduled for ${formatTime(dueDose.scheduled_at, dueDose.timezone)}`}</p>
          </>
        ) : lastConfirmed ? (
          <>
            <div className="dose-confirm-button dose-confirm-green" role="status" aria-live="polite">
              <span>DOSE CONFIRMED</span>
              <span>{data.next_dose ? "WAITING FOR" : "NO UPCOMING DOSE"}</span>
              {data.next_dose && <strong>{data.next_dose.medication_name}</strong>}
            </div>
            <h2>{lastConfirmed.medication_name} confirmed</h2>
            <p>{data.next_dose ? "Your next scheduled dose is shown above." : "There are no more upcoming doses on your current schedules."}</p>
          </>
        ) : data.next_dose ? (
          <div className="dose-confirm-neutral" role="status">
            WAITING FOR {data.next_dose.medication_name.toUpperCase()}
          </div>
        ) : (
          <div className="dose-confirm-neutral" role="status">NO MEDICINE DUE RIGHT NOW</div>
        )}
        {data.next_dose && <p className="next-dose-line">Next dose: {data.next_dose.medication_name} · {formatDateInTimezone(data.next_dose.scheduled_at, data.next_dose.timezone)} · {formatTime(data.next_dose.scheduled_at, data.next_dose.timezone)}</p>}
      </section>
      <section className="dashboard-section">
        <h2>Medication schedules</h2>
        {data.medications.length ? (
          <div className="patient-list">
            {data.medications.map((medication) => (
              <article className="patient-card" key={medication.id}>
                <div className="medication-row">
                  <span>
                    <strong>{medication.name}</strong><br />{medication.instructions || "Dose as prescribed"}<br />{medication.schedule_times.join(", ")} · {medication.timezone} · {medication.is_active ? "Active" : "Inactive"}
                  </span>
                  <div className="inline-actions">
                    <button
                      className="text-button"
                      onClick={() => setEditingMedicationId(
                        editingMedicationId === medication.id ? null : medication.id,
                      )}
                      type="button"
                    >
                      {editingMedicationId === medication.id ? "Close editor" : "Edit"}
                    </button>
                    {medication.is_active ? (
                      <button
                        className="text-button"
                        onClick={async () => {
                          if (window.confirm(`Deactivate ${medication.name}? Future reminders will be cancelled.`)) {
                            try {
                              await deactivateMedication(medication.id);
                              await refresh();
                            } catch (deactivateError) {
                              setError(deactivateError instanceof Error ? deactivateError.message : "Could not deactivate schedule.");
                            }
                          }
                        }}
                        type="button"
                      >
                        Deactivate
                      </button>
                    ) : (
                      <>
                        <button
                          className="text-button"
                          onClick={async () => {
                            if (medication.end_date && medication.end_date < currentDateInTimezone(medication.timezone)) {
                              setError("This schedule has ended. Edit its dates before resuming it.");
                              setEditingMedicationId(medication.id);
                              return;
                            }
                            try {
                              await updateMedication(medication.id, { is_active: true });
                              setMessage(`${medication.name} schedule resumed.`);
                              await refresh();
                            } catch (resumeError) {
                              setError(resumeError instanceof Error ? resumeError.message : "Could not resume schedule.");
                            }
                          }}
                          type="button"
                        >
                          Resume schedule
                        </button>
                        <button
                          className="text-button text-button-danger"
                          onClick={async () => {
                            if (window.confirm(`Permanently delete ${medication.name} and its dose history and call logs?`)) {
                              try {
                                await deleteMedication(medication.id);
                                setMessage(`${medication.name} schedule deleted.`);
                                await refresh();
                              } catch (deleteError) {
                                setError(deleteError instanceof Error ? deleteError.message : "Could not delete schedule.");
                              }
                            }
                          }}
                          type="button"
                        >
                          Delete permanently
                        </button>
                      </>
                    )}
                  </div>
                </div>
                {editingMedicationId === medication.id && (
                  <MedicationForm
                    medication={medication}
                    onCancel={() => setEditingMedicationId(null)}
                    onCreated={async () => {
                      setEditingMedicationId(null);
                      await refresh();
                    }}
                    timezone={data.user.timezone}
                  />
                )}
              </article>
            ))}
          </div>
        ) : (
          <p className="empty-state">Add a prescribed schedule above to see it here.</p>
        )}
      </section>
      <MedicationForm timezone={data.user.timezone} onCreated={refresh} />
      <section className="dashboard-section">
        <h2>Caregiver access</h2>
        <p>Share this invitation code privately with a caregiver to authorize access.</p>
        <div className="invitation-code">{data.invitation_code}</div>
        {data.caregivers.length ? (
          <ul className="simple-list">
            {data.caregivers.map((caregiver) => (
              <li key={caregiver.id}>
                {caregiver.name} · {caregiver.email} ({caregiver.label}){" "}
                <button
                  className="text-button"
                  onClick={async () => {
                    if (window.confirm(`Remove ${caregiver.name}'s access to your schedule?`)) {
                      try {
                        await unlinkCaregiver(caregiver.id);
                        await refresh();
                      } catch (unlinkError) {
                        setError(unlinkError instanceof Error ? unlinkError.message : "Could not remove caregiver access.");
                      }
                    }
                  }}
                  type="button"
                >
                  Remove access
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="field-hint">No caregiver is linked yet.</p>
        )}
      </section>
      <section className="dashboard-section">
        <h2>Optional automated voice reminders</h2>
        <p>
          Live calls are disabled unless you explicitly turn on consent. Without
          Twilio configuration, enabled reminders remain simulated and no phone
          will be called.
        </p>
        <div className="form-stack">
          <label>
            Phone number (international E.164 format)
            <input
              autoComplete="tel"
              onChange={(event) => setVoicePhone(event.target.value)}
              placeholder="+15551234567"
              type="tel"
              value={voicePhone}
            />
          </label>
          <p className="field-hint">
            Current setting: {voiceConsent?.enabled ? "consent is on" : "no call consent"} ·{" "}
            {voiceConsent?.provider_configured ? "Twilio configured" : "demo call mode"}
          </p>
          <p className="field-hint">
            With Twilio configured, a call is attempted at the scheduled dose
            time and one retry may be made after five minutes if the first call
            fails. Calls more than two minutes late are skipped after downtime.
          </p>
          {voiceConsent?.enabled ? (
            <div className="inline-actions">
              <button
                className="primary-button"
                disabled={voiceSaving || !voicePhone}
                onClick={() => saveVoiceSettings(true)}
                type="button"
              >
                {voiceSaving ? "Saving…" : "Save call settings"}
              </button>
              <button
                className="secondary-button"
                disabled={voiceSaving}
                onClick={() => saveVoiceSettings(false)}
                type="button"
              >
                {voiceSaving ? "Saving…" : "Withdraw call consent"}
              </button>
            </div>
          ) : (
            <button
              className="primary-button"
              disabled={voiceSaving || !voicePhone}
              onClick={() => {
                if (window.confirm("Enable automated medication reminder calls to this number? You can withdraw consent at any time.")) {
                  saveVoiceSettings(true);
                }
              }}
              type="button"
            >
              {voiceSaving ? "Saving…" : "I consent to automated calls"}
            </button>
          )}
          {voiceMessage && <p className="success-message" role="status">{voiceMessage}</p>}
        </div>
        <h3>Voice reminder history</h3>
        {voiceCallHistory.length ? (
          <ul className="simple-list">
            {voiceCallHistory.map((call) => (
              <li key={call.id}>
                Dose event {call.dose_event_id} · attempt {call.attempt_number} · {call.status} ·{" "}
                {new Date(call.attempt_at).toLocaleString()}
              </li>
            ))}
          </ul>
        ) : (
          <p className="empty-state">No automated voice attempts have been recorded.</p>
        )}
      </section>
      <details className="assistant-disclosure">
        <summary>MediMate assistant</summary>
        <VoiceAssistant />
      </details>
      <p className="safety-note">If you are unsure whether you took a dose, do not take an extra dose based on this app. Contact your caregiver or clinician.</p>
    </section>
  );
}

function CaregiverDashboard({ data, refresh }) {
  const [patientEmail, setPatientEmail] = useState("");
  const [invitationCode, setInvitationCode] = useState("");
  const [label, setLabel] = useState("Caregiver");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [linking, setLinking] = useState(false);
  const [editingMedicationId, setEditingMedicationId] = useState(null);

  async function linkPatient(event) {
    event.preventDefault();
    setError("");
    setMessage("");
    setLinking(true);
    try {
      await linkCaregiverPatient({
        patient_email: patientEmail,
        invitation_code: invitationCode,
        label,
      });
      setPatientEmail("");
      setInvitationCode("");
      setMessage("Patient linked. You can now view and manage the authorized schedule.");
      await refresh();
    } catch (linkError) {
      setError(linkError instanceof Error ? linkError.message : "Could not link patient.");
    } finally {
      setLinking(false);
    }
  }

  return (
    <section className="dashboard" aria-labelledby="dashboard-title">
      <div className="dashboard-heading">
        <div>
          <p className="eyebrow">Caregiver dashboard</p>
          <h1 id="dashboard-title">Hello, {data.user.name}.</h1>
          <p className="muted-copy">Only patients who explicitly share an invitation code appear here.</p>
        </div>
        <span className="demo-label">Local demo mode</span>
      </div>
      {message && <p className="success-message" role="status">{message}</p>}
      {error && <p className="error-message" role="alert">{error}</p>}
      <form className="link-patient-form" onSubmit={linkPatient}>
        <h2>Link a patient</h2>
        <p className="field-hint">Ask the patient to open their dashboard and share their invitation code privately.</p>
        <label>
          Patient email
          <input onChange={(event) => setPatientEmail(event.target.value)} required type="email" value={patientEmail} />
        </label>
        <label>
          Patient invitation code
          <input onChange={(event) => setInvitationCode(event.target.value)} required value={invitationCode} />
        </label>
        <label>
          Relationship label
          <input maxLength={80} onChange={(event) => setLabel(event.target.value)} required value={label} />
        </label>
        <button className="primary-button" disabled={linking} type="submit">
          {linking ? "Linking…" : "Link patient"}
        </button>
      </form>
      <section className="dashboard-section">
        <h2>Linked patients</h2>
        {data.patients.length ? (
          <div className="patient-list">
            {data.patients.map((patient) => (
              <article className="patient-card" key={patient.id}>
                <h3>{patient.name}</h3>
                <p className="muted-copy">{patient.email} · {patient.timezone}</p>
                <h4>Today’s events</h4>
                {patient.doses.length ? (
                  <ul className="simple-list">
                    {patient.doses.map((dose) => (
                      <li key={dose.id}>
                        {formatTime(dose.scheduled_at, dose.timezone)} · {dose.medication_name} · {dose.status.replaceAll("_", " ")}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="empty-state">No events today.</p>
                )}
                <h4>Medication schedules</h4>
                {patient.medications.map((medication) => (
                  <div className="medication-control" key={medication.id}>
                    <div className="medication-row">
                      <span>
                        {medication.name} · {medication.schedule_times.join(", ")} · {medication.timezone}
                        {!medication.is_active && " · inactive"}
                      </span>
                      <div className="inline-actions">
                          <button
                            className="text-button"
                            onClick={() => setEditingMedicationId(
                              editingMedicationId === medication.id ? null : medication.id,
                            )}
                            type="button"
                          >
                            {editingMedicationId === medication.id ? "Close editor" : "Edit"}
                          </button>
                          {medication.is_active ? (
                            <button
                              className="text-button"
                              onClick={async () => {
                                if (window.confirm(`Deactivate ${medication.name}? Future reminders will be cancelled.`)) {
                                  try {
                                    await deactivateMedication(medication.id);
                                    await refresh();
                                  } catch (deactivateError) {
                                    setError(deactivateError instanceof Error ? deactivateError.message : "Could not deactivate schedule.");
                                  }
                                }
                              }}
                              type="button"
                            >
                              Deactivate
                            </button>
                          ) : (
                            <>
                              <button
                                className="text-button"
                                onClick={async () => {
                                  if (medication.end_date && medication.end_date < currentDateInTimezone(medication.timezone)) {
                                    setError("This schedule has ended. Edit its dates before resuming it.");
                                    setEditingMedicationId(medication.id);
                                    return;
                                  }
                                  try {
                                    await updateMedication(medication.id, { is_active: true });
                                    setMessage(`${medication.name} schedule resumed.`);
                                    await refresh();
                                  } catch (resumeError) {
                                    setError(resumeError instanceof Error ? resumeError.message : "Could not resume schedule.");
                                  }
                                }}
                                type="button"
                              >
                                Resume schedule
                              </button>
                              <button
                                className="text-button text-button-danger"
                                onClick={async () => {
                                  if (window.confirm(`Permanently delete ${medication.name} and its dose history and call logs?`)) {
                                    try {
                                      await deleteMedication(medication.id);
                                      setMessage(`${medication.name} schedule deleted.`);
                                      await refresh();
                                    } catch (deleteError) {
                                      setError(deleteError instanceof Error ? deleteError.message : "Could not delete schedule.");
                                    }
                                  }
                                }}
                                type="button"
                              >
                                Delete permanently
                              </button>
                            </>
                          )}
                      </div>
                    </div>
                    {editingMedicationId === medication.id && (
                      <MedicationForm
                        medication={medication}
                        onCancel={() => setEditingMedicationId(null)}
                        onCreated={async () => {
                          setEditingMedicationId(null);
                          await refresh();
                        }}
                        patientId={patient.id}
                        timezone={patient.timezone}
                      />
                    )}
                  </div>
                ))}
                <MedicationForm
                  patientId={patient.id}
                  timezone={patient.timezone}
                  onCreated={refresh}
                />
              </article>
            ))}
          </div>
        ) : (
          <p className="empty-state">No patients are linked. Link one using their invitation code above.</p>
        )}
      </section>
    </section>
  );
}

function DashboardPage({ user }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    setError("");
    try {
      const result =
        user.role === "patient"
          ? await fetchPatientDashboard()
          : await fetchCaregiverDashboard();
      setData(result);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load your dashboard.");
    } finally {
      setIsLoading(false);
    }
  }, [user.role]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (user.role !== "patient") return undefined;
    const timer = window.setInterval(() => {
      refresh();
    }, 15_000);
    return () => window.clearInterval(timer);
  }, [refresh, user.role]);

  if (isLoading) return <p className="loading-state" role="status">Loading your dashboard…</p>;
  if (error && !data) {
    return (
      <section className="message-card">
        <h1>Dashboard unavailable</h1>
        <p className="error-message" role="alert">{error}</p>
        <button className="secondary-button" onClick={refresh} type="button">Try again</button>
      </section>
    );
  }

  return user.role === "patient" ? (
    <PatientDashboard data={data} refresh={refresh} />
  ) : (
    <CaregiverDashboard data={data} refresh={refresh} />
  );
}

export default DashboardPage;
