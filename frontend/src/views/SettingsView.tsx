"use client";

/**
 * Profile, password, appearance, presentation mode and sessions — only settings that actually do something.
 * Each group is its own clipped sheet; the forms put their action on a perforated strip at the bottom.
 */
import { useRouter } from "next/navigation";
import { useId, useState, type FormEvent, type ReactNode } from "react";

import { DeveloperSwitch, ThemeChoice } from "@/components/AppShell";
import { useToast } from "@/components/Toast";
import { Button, Field, InlineError, PageHeader, inputClass } from "@/components/ui";
import { api, isApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";

function Sheet({
  title,
  description,
  clip,
  footer,
  onSubmit,
  noValidate,
  children,
}: {
  title: string;
  description?: string;
  clip: "left" | "right";
  footer?: ReactNode;
  onSubmit?: (e: FormEvent) => void;
  noValidate?: boolean;
  children: ReactNode;
}) {
  const id = useId();
  const inner = (
    <>
      <span aria-hidden="true" className="hm-clip" style={clip === "left" ? { left: 40, right: "auto" } : undefined} />
      <header className="px-6 pt-8 sm:px-7">
        <h2 id={id} className="text-base text-fg">
          {title}
        </h2>
        {description && <p className="mt-0.5 text-xs text-muted">{description}</p>}
      </header>
      <div className="space-y-4 px-6 pt-4 pb-6 sm:px-7">{children}</div>
      {footer && <div className="hm-perforated flex flex-wrap items-center gap-3 px-6 py-4 sm:px-7">{footer}</div>}
    </>
  );
  const cls = "hm-clipped rounded-[3px]";
  return onSubmit ? (
    <form aria-labelledby={id} onSubmit={onSubmit} noValidate={noValidate} className={cls}>
      {inner}
    </form>
  ) : (
    <section aria-labelledby={id} className={cls}>
      {inner}
    </section>
  );
}

function Profile() {
  const { user, setUser } = useAuth();
  const toast = useToast();
  const [name, setName] = useState(user.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const id = useId();
  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await api.updateProfile(name.trim());
      setUser(me.user);
      toast("Profile saved.");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Sheet
      title="Profile"
      clip="right"
      onSubmit={save}
      footer={
        <Button type="submit" variant="primary" busy={busy} disabled={!name.trim() || name.trim() === user.name}>
          Save profile
        </Button>
      }
    >
      <Field label="Name" htmlFor={id}>
        {() => <input id={id} className={inputClass} value={name} maxLength={100} onChange={(e) => setName(e.target.value)} required />}
      </Field>
      <div>
        <p className="text-sm font-medium">Email address</p>
        <p className="text-sm text-fg-2">{user.email}</p>
        <p className="text-2xs text-muted">Member since {formatDateTime(user.created_at)}</p>
      </div>
      <InlineError error={error} />
    </Sheet>
  );
}

function Password() {
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<{ current?: string; next?: string; form?: string }>({});
  const ids = { current: useId(), next: useId() };
  async function save(e: FormEvent) {
    e.preventDefault();
    if (next.length < 10) {
      setErrors({ next: "Use at least 10 characters." });
      return;
    }
    setBusy(true);
    setErrors({});
    try {
      const r = await api.changePassword(current, next);
      setCurrent("");
      setNext("");
      toast(r.other_sessions_ended ? `Password changed. Signed out of ${r.other_sessions_ended} other session(s).` : "Password changed.");
    } catch (err) {
      if (isApiError(err) && err.field === "current_password") setErrors({ current: err.message });
      else if (isApiError(err) && err.field === "new_password") setErrors({ next: err.message });
      else setErrors({ form: err instanceof Error ? err.message : "Could not change the password." });
    } finally {
      setBusy(false);
    }
  }
  return (
    <Sheet
      title="Password"
      clip="left"
      onSubmit={save}
      noValidate
      footer={
        <Button type="submit" busy={busy} disabled={!current || !next}>
          Change password
        </Button>
      }
    >
      <Field label="Current password" htmlFor={ids.current} error={errors.current}>
        {({ describedBy, invalid }) => (
          <input id={ids.current} type="password" className={inputClass} value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" aria-describedby={describedBy} aria-invalid={invalid} maxLength={256} />
        )}
      </Field>
      <Field label="New password" htmlFor={ids.next} error={errors.next} hint="At least 10 characters. Other sessions are signed out.">
        {({ describedBy, invalid }) => (
          <input id={ids.next} type="password" className={inputClass} value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" aria-describedby={describedBy} aria-invalid={invalid} maxLength={256} />
        )}
      </Field>
      <InlineError error={errors.form} />
    </Sheet>
  );
}

function Sessions() {
  const { signOut } = useAuth();
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  return (
    <Sheet
      title="Sessions"
      clip="right"
      footer={
        <>
          <Button onClick={() => void signOut()}>Sign out</Button>
          <Button
            variant="quiet-danger"
            busy={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await api.logoutEverywhere();
                toast("Signed out everywhere.");
                router.replace("/login");
              } finally {
                setBusy(false);
              }
            }}
          >
            Sign out of all devices
          </Button>
        </>
      }
    >
      <p className="text-sm text-fg-2">You stay signed in on this device for 14 days of inactivity.</p>
      <p className="text-xs text-muted">Signing out of all devices also ends this session.</p>
    </Sheet>
  );
}

export function SettingsView() {
  return (
    <>
      <PageHeader title="Settings" />
      <div className="grid items-start gap-x-8 gap-y-12 pt-4 lg:grid-cols-2">
        <Profile />
        <Sheet title="Appearance" description="Saved in this browser." clip="left">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-sm">Theme</span>
            <ThemeChoice />
          </div>
          <DeveloperSwitch />
          <p className="text-2xs text-muted">Developer mode changes what is shown, never what you are allowed to do.</p>
        </Sheet>
        <Password />
        <Sessions />
      </div>
    </>
  );
}
