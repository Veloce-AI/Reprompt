import { useMutation } from "@tanstack/react-query";
import { requestMagicLink, setSessionToken, verifyMagicLink } from "@/lib/api";
import { Button } from "@/components/ui/button";

const DEFAULT_DEV_EMAIL = "dev@example.com";

/**
 * One-click sign-in for local development. The API's dev magic-link mode
 * (`REPROMPT_DEV_MAGIC_LINKS`, on by default locally — see
 * apps/api/src/reprompt_api/auth.py) returns the magic link directly in the
 * `/auth/request-link` response instead of emailing it; this button requests
 * a link and follows it in one go, so nobody has to copy-paste URLs just to
 * look at Settings on their own machine.
 *
 * Rendered only in Vite dev builds (`import.meta.env.DEV`) — a production
 * build compiles this to `null` regardless of the API's own flag, so the
 * normal email flow is the only path there. If the API turns out not to be
 * in dev mode (no `dev_magic_link` in the response), the button degrades to
 * an inline pointer at the normal flow rather than failing silently.
 */
export function DevSignInButton({
  email,
  onSignedIn,
}: {
  /** Optional email to sign in as; defaults to a fixed dev address. */
  email?: string;
  onSignedIn: () => void;
}) {
  const signInMutation = useMutation({
    mutationFn: async () => {
      const address = email?.trim() || DEFAULT_DEV_EMAIL;
      const requested = await requestMagicLink(address);
      if (!requested.dev_magic_link) {
        throw new Error(
          "The API isn't in dev magic-link mode — use the email sign-in flow instead."
        );
      }
      const token = new URL(requested.dev_magic_link).searchParams.get("token");
      if (!token) {
        throw new Error("The dev magic link is missing its token — check the API logs.");
      }
      const verified = await verifyMagicLink(token);
      setSessionToken(verified.session_token);
    },
    onSuccess: () => onSignedIn(),
  });

  if (!import.meta.env.DEV) return null;

  return (
    <div className="flex flex-col items-center gap-2">
      <Button
        type="button"
        variant="secondary"
        onClick={() => signInMutation.mutate()}
        disabled={signInMutation.isPending}
      >
        {signInMutation.isPending ? "Signing in…" : "Sign in (dev)"}
      </Button>
      <p className="text-11 text-ink-soft">
        Local dev shortcut — requests a magic link and follows it for you.
      </p>
      {signInMutation.isError && (
        <p className="text-12 text-parity-fail" role="alert">
          {signInMutation.error instanceof Error
            ? signInMutation.error.message
            : "Dev sign-in failed."}
        </p>
      )}
    </div>
  );
}
