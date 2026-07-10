import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { setSessionToken, verifyMagicLink } from "@/lib/api";

const MISSING_TOKEN_MESSAGE =
  "This link is missing its token. Request a new one from the sign-in page.";
const INVALID_LINK_MESSAGE = "This link is invalid or has expired.";

export default function AuthVerify() {
  const navigate = useNavigate();
  const { token } = useSearch({ from: "/auth/verify" });

  const [status, setStatus] = useState<"pending" | "error">(token ? "pending" : "error");
  const [message, setMessage] = useState(token ? "" : MISSING_TOKEN_MESSAGE);

  // Exchanging a magic link is a one-time, side-effecting action (the token
  // gets marked used server-side on first success) - guard against the
  // effect running twice for the same token (e.g. a fast-refresh remount).
  const startedForToken = useRef<string | null>(null);

  useEffect(() => {
    if (!token || startedForToken.current === token) return;
    startedForToken.current = token;

    verifyMagicLink(token)
      .then((result) => {
        setSessionToken(result.session_token);
        navigate({ to: "/" });
      })
      .catch((error) => {
        setStatus("error");
        setMessage(error instanceof Error ? error.message : INVALID_LINK_MESSAGE);
      });
  }, [token, navigate]);

  return (
    <div className="mx-auto max-w-md p-8 pt-24 text-center">
      {status === "pending" && (
        <p className="text-14 text-ink-soft" role="status">
          Signing you in…
        </p>
      )}
      {status === "error" && (
        <>
          <p className="text-14 text-parity-fail" role="alert">
            {message}
          </p>
          <a href="/login" className="mt-4 inline-block text-13 text-beam hover:underline">
            Back to sign in
          </a>
        </>
      )}
    </div>
  );
}
