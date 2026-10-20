import * as React from "react";
import { useEffect, useRef, useState } from "react";
import { sendAssistantMessage } from "../api/client.js";

function createRecognition() {
  if (typeof window === "undefined") return null;
  const Recognition = window.SpeechRecognition ?? window.webkitSpeechRecognition;
  if (!Recognition) return null;
  const recognition = new Recognition();
  recognition.lang = navigator.language || "en-US";
  recognition.continuous = false;
  recognition.interimResults = false;
  return recognition;
}

function VoiceAssistant() {
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [isListening, setIsListening] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const recognitionRef = useRef(null);
  const messagesEndRef = useRef(null);
  const speechSupported =
    typeof window !== "undefined" &&
    Boolean(window.SpeechRecognition ?? window.webkitSpeechRecognition);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ block: "nearest" });
  }, [messages]);

  useEffect(
    () => () => {
      recognitionRef.current?.stop();
      window.speechSynthesis?.cancel();
    },
    [],
  );

  function startListening() {
    setError("");
    setNotice("");
    const recognition = createRecognition();
    if (!recognition) {
      setError("Voice input is not supported in this browser. You can type below.");
      return;
    }
    recognitionRef.current = recognition;
    recognition.onstart = () => setIsListening(true);
    recognition.onend = () => setIsListening(false);
    recognition.onerror = (event) => {
      setIsListening(false);
      setError(
        event.error === "not-allowed"
          ? "Microphone access was denied. Allow microphone access in your browser settings or type your message."
          : "Voice input could not be completed. Please type your message.",
      );
    };
    recognition.onresult = (event) => {
      const recognizedText = event.results?.[0]?.[0]?.transcript;
      if (recognizedText) {
        setDraft(recognizedText);
        setNotice("Review the recognized words below, then choose Send.");
      }
    };
    try {
      recognition.start();
    } catch {
      setIsListening(false);
      setError("Voice input could not start. Please type your message instead.");
    }
  }

  function stopListening() {
    recognitionRef.current?.stop();
    setIsListening(false);
  }

  function speak(message) {
    if (!("speechSynthesis" in window)) {
      setError("Spoken playback is not supported in this browser.");
      return;
    }
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(message));
  }

  async function submit(event) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || isSending) return;
    setError("");
    setNotice("");
    const nextMessages = [...messages, { role: "user", content }];
    setMessages(nextMessages);
    setDraft("");
    setIsSending(true);
    try {
      const result = await sendAssistantMessage(nextMessages.slice(-12));
      setMessages([...nextMessages, { role: "assistant", content: result.reply }]);
    } catch (submitError) {
      setMessages(nextMessages);
      setDraft(content);
      setError(
        submitError instanceof Error ? submitError.message : "The assistant could not reply.",
      );
    } finally {
      setIsSending(false);
    }
  }

  return (
    <section className="assistant-card" aria-labelledby="assistant-heading">
      <div className="assistant-title">
        <div>
          <p className="eyebrow">Typed chat and optional voice</p>
          <h2 id="assistant-heading">MediMate assistant</h2>
        </div>
        <span className="demo-label">Never confirms a dose</span>
      </div>
      <p className="field-hint">
        The assistant can explain app features, not provide medical advice. If
        Nebius is configured, chat text is sent to Nebius; no medication
        schedules are attached. Voice is never started automatically.
      </p>
      <div className="chat-transcript" aria-live="polite" aria-label="Assistant conversation">
        {!messages.length && (
          <p className="empty-state">
            Try asking: “What does due mean?” or “How do I link a caregiver?”
          </p>
        )}
        {messages.map((message, index) => (
          <div className={`chat-message chat-${message.role}`} key={`${index}-${message.role}`}>
            <strong>{message.role === "user" ? "You" : "MediMate"}</strong>
            <p>{message.content}</p>
            {message.role === "assistant" && (
              <button
                className="text-button"
                onClick={() => speak(message.content)}
                type="button"
              >
                Read reply aloud
              </button>
            )}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>
      <div className="voice-controls">
        {!isListening ? (
          <button
            className="secondary-button"
            disabled={!speechSupported || isSending}
            onClick={startListening}
            type="button"
          >
            Start microphone
          </button>
        ) : (
          <button className="danger-button" onClick={stopListening} type="button">
            Stop listening
          </button>
        )}
        <span role="status">
          {isListening ? "Listening now — speak, then review the text before sending." : "Microphone off"}
        </span>
      </div>
      {!speechSupported && (
        <p className="field-hint">Speech recognition is unavailable in this browser; typed chat remains available.</p>
      )}
      <form className="chat-form" onSubmit={submit}>
        <label className="visually-hidden" htmlFor="assistant-message">Type a message</label>
        <textarea
          id="assistant-message"
          maxLength={1000}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Type a question or review recognized text…"
          rows={2}
          value={draft}
        />
        <button className="primary-button" disabled={isSending || !draft.trim()} type="submit">
          {isSending ? "Sending…" : "Send"}
        </button>
      </form>
      {notice && <p className="success-message" role="status">{notice}</p>}
      {error && <p className="error-message" role="alert">{error}</p>}
    </section>
  );
}

export default VoiceAssistant;
