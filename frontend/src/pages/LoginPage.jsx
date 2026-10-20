import * as React from "react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { signIn, signUp } from "../api/client.js";

function LoginPage({ onAuthenticated }) {
  const navigate = useNavigate();
  const [mode, setMode] = useState("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(true);
  const [role, setRole] = useState("patient");
  const [timezone, setTimezone] = useState(
    Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  );
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      const session =
        mode === "register"
          ? await signUp({ name, email, password, role, timezone, remember_me: rememberMe })
          : await signIn(email, password, rememberMe);
      onAuthenticated(session);
      navigate("/dashboard", { replace: true });
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : "Could not sign in. Please try again.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="auth-card" aria-labelledby="login-heading">
      <p className="eyebrow">Your medication companion</p>
      <h1 id="login-heading">
        {mode === "login" ? "Welcome back." : "Create your account."}
      </h1>
      <p className="muted-copy">
        {mode === "login"
          ? "Sign in to open your patient or caregiver dashboard."
          : "Choose patient or caregiver. A patient must share an invitation code to authorize a caregiver."}
      </p>
      <form className="form-stack" onSubmit={handleSubmit}>
        {mode === "register" && (
          <>
            <label>
              Name
              <input
                autoComplete="name"
                maxLength={120}
                onChange={(event) => setName(event.target.value)}
                required
                value={name}
              />
            </label>
            <label>
              Account type
              <select value={role} onChange={(event) => setRole(event.target.value)}>
                <option value="patient">Patient</option>
                <option value="caregiver">Caregiver</option>
              </select>
            </label>
            <label>
              Time zone
              <input
                autoComplete="off"
                onChange={(event) => setTimezone(event.target.value)}
                required
                value={timezone}
              />
              <span className="field-hint">Use an IANA name such as America/Los_Angeles.</span>
            </label>
          </>
        )}
        <label>
          Email
          <input
            autoComplete="email"
            onChange={(event) => setEmail(event.target.value)}
            required
            type="email"
            value={email}
          />
        </label>
        <label className="remember-choice">
          <input checked={rememberMe} onChange={(event) => setRememberMe(event.target.checked)} type="checkbox" />
          Keep me signed in on this device
        </label>
        <label>
          Password
          <input
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            minLength={mode === "register" ? 10 : 1}
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
          {mode === "register" && (
            <span className="field-hint">Use at least 10 characters.</span>
          )}
        </label>
        {error && <p className="error-message" role="alert">{error}</p>}
        <button className="primary-button" disabled={isSubmitting} type="submit">
          {isSubmitting
            ? "Please wait…"
            : mode === "login"
              ? "Sign in"
              : "Create account"}
        </button>
      </form>
      <p className="switch-mode">
        {mode === "login" ? "New to MediMate?" : "Already have an account?"}{" "}
        <button
          className="inline-button"
          onClick={() => {
            setError("");
            setMode(mode === "login" ? "register" : "login");
          }}
          type="button"
        >
          {mode === "login" ? "Create an account" : "Sign in"}
        </button>
      </p>
      <p className="safety-note">
        Hackathon prototype only. Do not use this service to make medication
        decisions or for emergencies.
      </p>
    </section>
  );
}

export default LoginPage;
