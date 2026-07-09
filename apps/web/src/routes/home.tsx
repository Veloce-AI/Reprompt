import { Link } from "@tanstack/react-router";

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-8">
      <h1 className="font-display text-40 font-semibold leading-display text-ink">
        Refract
      </h1>
      <p className="text-16 text-ink-soft">
        Model migration parity engine
      </p>
      <Link
        to="/dev/kit"
        className="mt-4 rounded-control bg-beam px-4 py-2 text-14 font-medium text-paper transition-colors duration-fast ease-out hover:brightness-110 focus-visible:shadow-[var(--focus-ring)]"
      >
        View design kit
      </Link>
    </div>
  );
}
