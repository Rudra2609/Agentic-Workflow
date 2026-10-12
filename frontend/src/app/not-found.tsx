import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-md px-4 py-24 text-center">
      <p className="font-mono text-xs text-muted">404</p>
      <h1 className="mt-2 text-xl font-semibold">This page doesn&apos;t exist</h1>
      <p className="mt-2 text-sm text-fg-2">
        It may have been moved, or the project was deleted.{" "}
        <Link className="text-accent-ink underline-offset-2 hover:underline" href="/">
          Go to your projects
        </Link>
      </p>
    </div>
  );
}
