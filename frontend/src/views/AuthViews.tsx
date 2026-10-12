"use client";

/** Sign in, create account, forgot password, reset password. The server re-validates everything. */
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useId, useState, type FormEvent, type ReactNode } from "react";

import { Button, Field, InlineError, cx, inputClass } from "@/components/ui";
import { api, isApiError } from "@/lib/api";
import { safeNext } from "@/lib/auth";

const MIN_PASSWORD = 10;
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/;

type Errors = Partial<Record<"name" | "email" | "password" | "confirm" | "form", string>>;

function Header({ title, subtitle }: { title: string; subtitle: ReactNode }) {
  return (
    <div className="mb-7">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-1 text-sm text-fg-2">{subtitle}</p>
    </div>
  );
}

/** Eye = "show the password"; eye with a slash = "hide it" (the convention most sites use). */
function EyeIcon({ open }: { open: boolean }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="size-[18px]" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2.5 12s3.5-6.5 9.5-6.5S21.5 12 21.5 12s-3.5 6.5-9.5 6.5S2.5 12 2.5 12Z" />
      <circle cx="12" cy="12" r="3" />
      {!open && <path d="M4 4l16 16" />}
    </svg>
  );
}

function PasswordInput({
  id,
  value,
  onChange,
  autoComplete,
  describedBy,
  invalid,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete: string;
  describedBy?: string;
  invalid: boolean;
}) {
  const [shown, setShown] = useState(false);
  return (
    <div className="relative">
      <input
        id={id}
        type={shown ? "text" : "password"}
        className={cx(inputClass, "pr-11")}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        aria-describedby={describedBy}
        aria-invalid={invalid}
        maxLength={256}
        required
      />
      <button
        type="button"
        onClick={() => setShown((s) => !s)}
        aria-label={shown ? "Hide password" : "Show password"}
        aria-pressed={shown}
        title={shown ? "Hide password" : "Show password"}
        className="absolute inset-y-1 right-1 grid w-8 place-items-center rounded-md text-muted transition-colors hover:bg-hover hover:text-fg"
      >
        <EyeIcon open={!shown} />
      </button>
    </div>
  );
}

/** Map an API error to a field (accounts API sends {message, field}) or the form. */
function apiErrors(err: unknown, fields: Record<string, keyof Errors> = {}): Errors {
  if (isApiError(err)) {
    if (err.kind === "network") return { form: "Can't reach the HMAP server. Check that it is running and try again." };
    const field = err.field ? (fields[err.field] ?? (err.field as keyof Errors)) : null;
    if (field) return { [field]: err.message };
    return { form: err.message };
  }
  return { form: "Something went wrong. Please try again." };
}

// ------------------------------------------------------------------ sign in

export function LoginView() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const ids = { email: useId(), password: useId() };

  async function submit(e: FormEvent) {
    e.preventDefault();
    const v: Errors = {};
    if (!EMAIL.test(email.trim())) v.email = "Enter the email address you signed up with.";
    if (!password) v.password = "Enter your password.";
    setErrors(v);
    if (Object.keys(v).length) return;
    setBusy(true);
    try {
      await api.login(email.trim(), password);
      router.replace(next);
    } catch (err) {
      setErrors(apiErrors(err));
      setBusy(false);
    }
  }

  return (
    <>
      <Header title="Welcome back" subtitle="Sign in to continue where you left off." />
      {params.get("reset") === "1" && (
        <p role="status" className="mb-5 border-l-2 border-success bg-success-soft px-3 py-2 text-sm">
          Your password was changed. Sign in with the new one.
        </p>
      )}
      <form onSubmit={submit} noValidate className="space-y-4">
        <Field label="Email address" htmlFor={ids.email} error={errors.email}>
          {({ describedBy, invalid }) => (
            <input
              id={ids.email}
              type="email"
              className={inputClass}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              aria-describedby={describedBy}
              aria-invalid={invalid}
              maxLength={254}
              autoFocus
              required
            />
          )}
        </Field>
        <Field
          label="Password"
          htmlFor={ids.password}
          error={errors.password}
          trailing={
            <Link href="/forgot-password" className="text-xs text-accent-ink hover:underline">
              Forgot password?
            </Link>
          }
        >
          {({ describedBy, invalid }) => (
            <PasswordInput id={ids.password} value={password} onChange={setPassword} autoComplete="current-password" describedBy={describedBy} invalid={invalid} />
          )}
        </Field>
        <InlineError error={errors.form} />
        <Button type="submit" variant="primary" busy={busy} className="w-full">
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
      <p className="mt-6 text-sm text-fg-2">
        New to HMAP?{" "}
        <Link href={`/register${next !== "/" ? `?next=${encodeURIComponent(next)}` : ""}`} className="font-medium text-accent-ink hover:underline">
          Create an account
        </Link>
      </p>
    </>
  );
}

// ------------------------------------------------------------------ create account

export function RegisterView() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const ids = { name: useId(), email: useId(), password: useId(), confirm: useId() };

  async function submit(e: FormEvent) {
    e.preventDefault();
    const v: Errors = {};
    if (!name.trim()) v.name = "Enter your name.";
    if (!EMAIL.test(email.trim())) v.email = "Enter a valid email address.";
    if (password.length < MIN_PASSWORD) v.password = `Use at least ${MIN_PASSWORD} characters.`;
    if (confirm !== password) v.confirm = "The passwords don't match.";
    setErrors(v);
    if (Object.keys(v).length) return;
    setBusy(true);
    try {
      await api.register(name.trim(), email.trim(), password);
      router.replace(next);
    } catch (err) {
      setErrors(apiErrors(err));
      setBusy(false);
    }
  }

  return (
    <>
      <Header title="Create your account" subtitle="Your projects are private to your account." />
      <form onSubmit={submit} noValidate className="space-y-4">
        <Field label="Name" htmlFor={ids.name} error={errors.name}>
          {({ describedBy, invalid }) => (
            <input id={ids.name} className={inputClass} value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" aria-describedby={describedBy} aria-invalid={invalid} maxLength={100} autoFocus required />
          )}
        </Field>
        <Field label="Email address" htmlFor={ids.email} error={errors.email}>
          {({ describedBy, invalid }) => (
            <input id={ids.email} type="email" className={inputClass} value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" aria-describedby={describedBy} aria-invalid={invalid} maxLength={254} required />
          )}
        </Field>
        <Field label="Password" htmlFor={ids.password} error={errors.password} hint={`At least ${MIN_PASSWORD} characters. A short phrase works well.`}>
          {({ describedBy, invalid }) => (
            <PasswordInput id={ids.password} value={password} onChange={setPassword} autoComplete="new-password" describedBy={describedBy} invalid={invalid} />
          )}
        </Field>
        <Field label="Confirm password" htmlFor={ids.confirm} error={errors.confirm}>
          {({ describedBy, invalid }) => (
            <PasswordInput id={ids.confirm} value={confirm} onChange={setConfirm} autoComplete="new-password" describedBy={describedBy} invalid={invalid} />
          )}
        </Field>
        <InlineError error={errors.form} />
        <Button type="submit" variant="primary" busy={busy} className="w-full">
          {busy ? "Creating account…" : "Create account"}
        </Button>
      </form>
      <p className="mt-6 text-sm text-fg-2">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-accent-ink hover:underline">
          Sign in
        </Link>
      </p>
    </>
  );
}

// ------------------------------------------------------------------ forgot / reset

export function ForgotPasswordView() {
  const [email, setEmail] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const id = useId();

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!EMAIL.test(email.trim())) {
      setErrors({ email: "Enter a valid email address." });
      return;
    }
    setErrors({});
    setBusy(true);
    try {
      await api.forgotPassword(email.trim());
      setSent(true);
    } catch (err) {
      setErrors(apiErrors(err));
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <>
        <Header title="Check your email" subtitle="If an account exists for that address, we've sent a link to reset the password. It works for 30 minutes." />
        <p className="text-sm text-muted">
          Running HMAP locally without an email service? The message is saved in <code className="font-mono text-xs">data/dev_mailbox/</code> on the server.
        </p>
        <p className="mt-6 text-sm">
          <Link href="/login" className="font-medium text-accent-ink hover:underline">
            Back to sign in
          </Link>
        </p>
      </>
    );
  }
  return (
    <>
      <Header title="Reset your password" subtitle="Enter your email address and we'll send you a link to choose a new password." />
      <form onSubmit={submit} noValidate className="space-y-4">
        <Field label="Email address" htmlFor={id} error={errors.email}>
          {({ describedBy, invalid }) => (
            <input id={id} type="email" className={inputClass} value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" aria-describedby={describedBy} aria-invalid={invalid} maxLength={254} autoFocus required />
          )}
        </Field>
        <InlineError error={errors.form} />
        <Button type="submit" variant="primary" busy={busy} className="w-full">
          Send reset link
        </Button>
      </form>
      <p className="mt-6 text-sm">
        <Link href="/login" className="text-accent-ink hover:underline">
          Back to sign in
        </Link>
      </p>
    </>
  );
}

export function ResetPasswordView() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const ids = { password: useId(), confirm: useId() };

  useEffect(() => {
    // The token is in the URL fragment (#token=…), which browsers never send to a server. Remove it from the address bar.
    const match = /(?:^|[#&])token=([A-Za-z0-9_-]+)/.exec(window.location.hash);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- read once after hydration
    setToken(match?.[1] ?? "");
    if (match) window.history.replaceState(null, "", window.location.pathname);
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const v: Errors = {};
    if (password.length < MIN_PASSWORD) v.password = `Use at least ${MIN_PASSWORD} characters.`;
    if (confirm !== password) v.confirm = "The passwords don't match.";
    setErrors(v);
    if (Object.keys(v).length || !token) return;
    setBusy(true);
    try {
      await api.resetPassword(token, password);
      router.replace("/login?reset=1");
    } catch (err) {
      setErrors(apiErrors(err));
      setBusy(false);
    }
  }

  if (token === "") {
    return (
      <>
        <Header title="This link isn't valid" subtitle="Reset links work once and expire after 30 minutes." />
        <Link href="/forgot-password" className="text-sm font-medium text-accent-ink hover:underline">
          Request a new link
        </Link>
      </>
    );
  }
  return (
    <>
      <Header title="Choose a new password" subtitle="You'll be signed out everywhere and can sign in with the new password." />
      <form onSubmit={submit} noValidate className="space-y-4">
        <Field label="New password" htmlFor={ids.password} error={errors.password} hint={`At least ${MIN_PASSWORD} characters.`}>
          {({ describedBy, invalid }) => (
            <PasswordInput id={ids.password} value={password} onChange={setPassword} autoComplete="new-password" describedBy={describedBy} invalid={invalid} />
          )}
        </Field>
        <Field label="Confirm new password" htmlFor={ids.confirm} error={errors.confirm}>
          {({ describedBy, invalid }) => (
            <PasswordInput id={ids.confirm} value={confirm} onChange={setConfirm} autoComplete="new-password" describedBy={describedBy} invalid={invalid} />
          )}
        </Field>
        <InlineError error={errors.form} />
        <Button type="submit" variant="primary" busy={busy} disabled={token === null} className="w-full">
          Save new password
        </Button>
      </form>
    </>
  );
}
