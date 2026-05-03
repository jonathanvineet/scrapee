// frontend/feedback.js
// Lightweight helper to send implicit feedback to the backend

export async function sendFeedback(sources = [], success = true, query = "") {
  try {
    await fetch("/api/mcp/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sources, success, query }),
    });
  } catch (e) {
    // Non-fatal: feedback is best-effort
    console.warn("Feedback failed:", e);
  }
}

// Example usage:
// import { sendFeedback } from './feedback.js'
//
// // After rendering MCP response:
// sendFeedback(response.sources || [], true, userQuery)
//
// // On retry or if user asks again:
// sendFeedback(previousSources, false, previousQuery)

// Optional: time-on-page heuristic
export function sendTimedFeedback(sources = [], query = "", thresholdMs = 4000) {
  const start = Date.now();
  return () => {
    const duration = Date.now() - start;
    const success = duration >= thresholdMs;
    sendFeedback(sources, success, query);
  };
}
