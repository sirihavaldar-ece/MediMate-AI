import * as React from "react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { checkBackendHealth } from "../api/client.js";

function HomePage({ user }) {
  const [status, setStatus] = useState("Not checked yet");
  const [isChecking, setIsChecking] = useState(false);

  async function handleHealthCheck() {
    setIsChecking(true);
    setStatus("Checking backend…");
    try {
      const result = await checkBackendHealth();
      setStatus(`Connected — ${result.status}`);
    } catch (error) {
      setStatus(
        error instanceof Error ? error.message : "Could not reach the backend.",
      );
    } finally {
      setIsChecking(false);
    }
  }

  return (
    <section className="hero" aria-labelledby="welcome-heading">
      <p className="eyebrow">A little support, right on schedule</p>
      <h1 id="welcome-heading">Your medication routine, made easier.</h1>
      <p className="hero-copy">
        MediMate AI is being built to help patients and caregivers keep track of
        prescribed medication schedules and reminders.
      </p>
      <div className="health-panel">
        {user ? (
          <Link className="primary-button" to="/dashboard">Open my dashboard</Link>
        ) : (
          <>
            <Link className="primary-button" to="/login">Sign in or create an account</Link>
            <button
              className="secondary-button"
              type="button"
              onClick={handleHealthCheck}
              disabled={isChecking}
            >
              {isChecking ? "Checking…" : "Check backend connection"}
            </button>
          </>
        )}
        <p role="status" aria-live="polite">{status}</p>
      </div>
      <p className="safety-note">
        This prototype does not provide medical advice. Always follow your
        clinician’s instructions.
      </p>
    </section>
  );
}

export default HomePage;
