import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { requestMagicLink } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DevSignInButton } from "@/components/dev-sign-in-button";

export default function Login() {
  const [email, setEmail] = useState("");
  const navigate = useNavigate();

  const requestLinkMutation = useMutation({
    mutationFn: (email: string) => requestMagicLink(email),
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = email.trim();
    if (!trimmed) return;
    requestLinkMutation.mutate(trimmed);
  }

  return (
    <div className="mx-auto flex max-w-md flex-col gap-6 p-8 pt-24">
      <div>
        <h1 className="font-display text-28 font-semibold leading-display text-ink">Sign in</h1>
        <p className="mt-1 text-14 text-ink-soft">
          Enter your email and we&apos;ll send you a one-time sign-in link — no password needed.
        </p>
      </div>

      {!requestLinkMutation.isSuccess && (
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <label htmlFor="login-email" className="text-13 font-medium text-ink">
            Email address
          </label>
          <Input
            id="login-email"
            name="email"
            type="email"
            autoComplete="email"
            required
            placeholder="you@company.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <Button type="submit" variant="primary" disabled={requestLinkMutation.isPending}>
            {requestLinkMutation.isPending ? "Sending magic link…" : "Send magic link"}
          </Button>
          {requestLinkMutation.isError && (
            <p className="text-13 text-parity-fail" role="alert">
              {requestLinkMutation.error instanceof Error
                ? requestLinkMutation.error.message
                : "Couldn't send the link. Check the address and try again."}
            </p>
          )}
        </form>
      )}

      {!requestLinkMutation.isSuccess && (
        <div className="border-t border-line pt-4">
          <DevSignInButton
            email={email}
            onSignedIn={() => navigate({ to: "/pipelines" })}
          />
        </div>
      )}

      {requestLinkMutation.isSuccess && (
        <Card>
          <CardHeader>
            <CardTitle>Check your email for a link</CardTitle>
            <CardDescription>
              If {email} can receive mail, a sign-in link is on its way. Click it to continue.
            </CardDescription>
          </CardHeader>
          {requestLinkMutation.data.dev_magic_link && (
            <CardContent className="space-y-2 border-t border-line pt-4">
              <p className="text-12 text-ink-soft">
                Dev-only fallback: no email provider is configured in this environment yet, so
                the link is shown here instead of actually being sent.
              </p>
              <a
                href={requestLinkMutation.data.dev_magic_link}
                className="block break-all font-mono text-13 text-beam hover:underline"
              >
                {requestLinkMutation.data.dev_magic_link}
              </a>
            </CardContent>
          )}
        </Card>
      )}
    </div>
  );
}
