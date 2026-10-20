const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function csrfToken() {
  return document.cookie.split(";").map((item) => item.trim()).find((item) => item.startsWith("medimate_csrf="))?.split("=").slice(1).join("=");
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers);
  headers.set("X-Auth-Mode", "cookie");
  const csrf = csrfToken();
  if (csrf && options.method && options.method !== "GET") headers.set("X-CSRF-Token", decodeURIComponent(csrf));
  if (options.body) headers.set("Content-Type", "application/json");

  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers, credentials: "include" });
  } catch {
    throw new Error("Cannot connect to the backend. Check that the API server is running.");
  }
  if (!response.ok) {
    let message = `Request failed (HTTP ${response.status}).`;
    try {
      const payload = await response.json();
      const detail = payload.detail;
      if (typeof detail === "string") message = detail;
      else if (Array.isArray(detail)) {
        message = detail.map((item) => item.msg).join(" ");
      }
    } catch {
      // Keep the readable HTTP status when the server did not return JSON.
    }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return null;
  return response.json();
}

export function checkBackendHealth() {
  return request("/health");
}

export function getCurrentUser() {
  return request("/auth/me");
}

export function signOut() {
  return request("/auth/logout", { method: "POST" });
}

export function signIn(email, password, rememberMe) {
  return request("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password, remember_me: rememberMe }),
  });
}

export function signUp(values) {
  return request("/auth/register", {
    method: "POST",
    body: JSON.stringify(values),
  });
}

export function fetchPatientDashboard() {
  return request("/dashboard/patient");
}

export function fetchCaregiverDashboard() {
  return request("/dashboard/caregiver");
}

export function createMedication(values) {
  return request("/medications", {
    method: "POST",
    body: JSON.stringify(values),
  });
}

export function updateMedication(id, values) {
  return request(`/medications/${id}`, {
    method: "PUT",
    body: JSON.stringify(values),
  });
}

export function deactivateMedication(id) {
  return request(`/medications/${id}`, { method: "DELETE" });
}

export function deleteMedication(id) {
  return request(`/medications/${id}?permanent=true`, { method: "DELETE" });
}

export function confirmDose(id) {
  return request(`/doses/${id}/confirm`, { method: "POST" });
}

export function remindAgain(id) {
  return request(`/doses/${id}/remind-again`, { method: "POST" });
}

export function askForHelp(id) {
  return request(`/doses/${id}/need-help`, { method: "POST" });
}

export function linkCaregiverPatient(values) {
  return request("/auth/caregivers/link", {
    method: "POST",
    body: JSON.stringify(values),
  });
}

export function unlinkCaregiver(caregiverId) {
  return request(`/auth/caregivers/${caregiverId}`, { method: "DELETE" });
}

export function fetchIntegrationStatus() {
  return request("/integrations/status");
}

export function sendAssistantMessage(messages) {
  return request("/assistant/chat", {
    method: "POST",
    body: JSON.stringify({ messages }),
  });
}

export function testNebiusIntegration() {
  return request("/integrations/nebius/test", { method: "POST" });
}

export function testVoiceIntegration(values = {}) {
  return request("/integrations/voice/test", {
    method: "POST",
    body: JSON.stringify(values),
  });
}

export function fetchVoiceConsent() {
  return request("/integrations/voice/consent");
}

export function saveVoiceConsent(values) {
  return request("/integrations/voice/consent", {
    method: "PUT",
    body: JSON.stringify(values),
  });
}

export function fetchVoiceCallHistory() {
  return request("/integrations/voice/history");
}
