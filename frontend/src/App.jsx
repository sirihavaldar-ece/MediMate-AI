import * as React from "react";
import { useEffect, useState } from "react";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";
import { ApiError, getCurrentUser, signOut } from "./api/client.js";
import DashboardPage from "./pages/DashboardPage.jsx";
import HomePage from "./pages/HomePage.jsx";
import InstallPrompt from "./components/InstallPrompt.jsx";
import LoginPage from "./pages/LoginPage.jsx";
import "./styles/global.css";

function App() {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [authNotice, setAuthNotice] = useState("");

  useEffect(() => {
    getCurrentUser()
      .then(setUser)
      .catch((error) => {
        if (error instanceof ApiError && error.status === 401) {
        } else {
          setAuthNotice(
            "Could not verify your session because the backend is unavailable. Your session has been kept; try again after reconnecting.",
          );
        }
      })
      .finally(() => setIsLoading(false));
  }, []);

  function handleAuthenticated(session) {
    setUser(session.user);
  }

  async function handleSignOut() {
    setAuthNotice("");
    try {
      await signOut();
    } catch {
      setAuthNotice(
        "You were signed out in this browser, but the server could not revoke the session. It will expire automatically.",
      );
    } finally {
      setUser(null);
    }
  }

  return (
    <BrowserRouter>
      <div className="app-shell">
        <header className="site-header">
          <Link className="brand" to="/">
            <span className="brand-mark" aria-hidden="true">+</span>
            MediMate AI
          </Link>
          <nav aria-label="Main navigation">
            <Link to="/">Home</Link>
            {user ? (
              <>
                <Link to="/dashboard">Dashboard</Link>
                <button className="text-button" type="button" onClick={handleSignOut}>
                  Sign out
                </button>
              </>
            ) : (
              <Link to="/login">Sign in</Link>
            )}
          </nav>
        </header>
        {authNotice && <p className="error-message auth-notice" role="alert">{authNotice}</p>}
        <main>
          <Routes>
            <Route path="/" element={<HomePage user={user} />} />
            <Route
              path="/login"
              element={
                isLoading ? (
                  <p className="loading-state" role="status">Checking your saved sign-in…</p>
                ) : user ? (
                  <Navigate to="/dashboard" replace />
                ) : (
                  <LoginPage onAuthenticated={handleAuthenticated} />
                )
              }
            />
            <Route
              path="/dashboard"
              element={
                isLoading ? (
                  <p role="status">Loading your account…</p>
                ) : user ? (
                  <DashboardPage user={user} />
                ) : (
                  <Navigate to="/login" replace />
                )
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
        <InstallPrompt />
        <footer className="site-footer">
          Prototype only · Follow your clinician’s instructions for medication.
        </footer>
      </div>
    </BrowserRouter>
  );
}

export default App;
