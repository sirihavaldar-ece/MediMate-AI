import * as React from "react";
import { useEffect, useState } from "react";
import { testNebiusIntegration, testVoiceIntegration, fetchIntegrationStatus } from "../api/client.js";
import VoiceAssistant from "../components/VoiceAssistant.jsx";

function AssistantPage() {
  const [status, setStatus] = useState(null);
  const [result, setResult] = useState("");
  const [error, setError] = useState("");
  const [isTesting, setIsTesting] = useState(false);
  const [voiceResult, setVoiceResult] = useState("");

  useEffect(() => {
    fetchIntegrationStatus()
      .then(setStatus)
      .catch((loadError) => setError(
        loadError instanceof Error ? loadError.message : "Could not load integration status.",
      ));
  }, []);

  async function testAi() {
    setIsTesting(true);
    setError("");
    setResult("");
    try {
      const response = await testNebiusIntegration();
      setResult(
        `${response.mode === "nebius" ? "Nebius connection succeeded" : "Mock mode is ready"} · ${response.model}: ${response.message}`,
      );
      setStatus(await fetchIntegrationStatus());
    } catch (testError) {
      setError(testError instanceof Error ? testError.message : "AI test failed.");
    } finally {
      setIsTesting(false);
    }
  }

  async function testVoice() {
    setError("");
    try {
      const response = await testVoiceIntegration();
      setVoiceResult(response.message);
    } catch (testError) {
      setError(testError instanceof Error ? testError.message : "Voice integration test failed.");
    }
  }

  return (
    <section className="dashboard assistant-page" aria-labelledby="assistant-page-heading">
      <div className="dashboard-heading">
        <div>
          <p className="eyebrow">Phase 3 · AI and voice</p>
          <h1 id="assistant-page-heading">Assistant and integrations</h1>
          <p className="muted-copy">Test Nebius Token Factory without exposing your API key in the browser.</p>
        </div>
        <span className="demo-label">{status?.ai_mode === "nebius" ? "Nebius live" : "AI mock mode"}</span>
      </div>
      {status && (
        <section className="dashboard-section integration-status" aria-labelledby="integration-status-heading">
          <h2 id="integration-status-heading">Integration status</h2>
          <dl>
            <div><dt>AI provider</dt><dd>{status.ai_configured ? "Nebius Token Factory configured" : "Local mock (no API key configured)"}</dd></div>
            <div><dt>Nemotron model</dt><dd>{status.ai_model}</dd></div>
            <div><dt>Voice reminders</dt><dd>{status.voice_configured ? "Twilio credentials configured" : "Demo mode (no outbound calls)"}</dd></div>
          </dl>
          <button className="primary-button" disabled={isTesting} onClick={testAi} type="button">
            {isTesting ? "Testing…" : "Test Nebius AI"}
          </button>
          {result && <p className="success-message" role="status">{result}</p>}
          <p className="field-hint">
            A test in mock mode does not contact Nebius. To enable live inference,
            add NEBIUS_API_KEY privately in the backend .env file and restart the API.
          </p>
        </section>
      )}
      <section className="dashboard-section" aria-labelledby="voice-test-heading">
        <h2 id="voice-test-heading">Outbound voice test</h2>
        <p>With no Twilio credentials, this test only records a simulated result and will not call a phone.</p>
        <button className="secondary-button" onClick={testVoice} type="button">Run demo call test</button>
        {voiceResult && <p className="success-message" role="status">{voiceResult}</p>}
        <p className="field-hint">
          Live calls require provider credentials, a valid verified destination,
          recipient consent, and a separate explicit confirmation. Local calling
          eligibility, pricing, and regulations vary; no live call is initiated here.
        </p>
      </section>
      {error && <p className="error-message" role="alert">{error}</p>}
      <VoiceAssistant />
    </section>
  );
}

export default AssistantPage;
