import { useEffect, useState } from "react";
import {
  NavLink,
  Outlet,
  ScrollRestoration,
  useLocation,
} from "react-router-dom";
import { Menu, Settings, X } from "lucide-react";
import { api } from "@/lib/api";
import { useOnMount } from "@/lib/hooks";
import { cn } from "@/lib/cn";
import { Mono } from "@/components/ui";
import { DigitHalftone } from "@/components/decor";

const NAV = [
  { to: "/inspection", label: "Inspection" },
  { to: "/standards", label: "Standards" },
  { to: "/certification", label: "Certification" },
  { to: "/laboratories", label: "Laboratories" },
  { to: "/hallmarking", label: "Hallmarking" },
  { to: "/review", label: "Review" },
  { to: "/history", label: "History" },
];

/* --------------------------------------------------------------- wordmark --- */

export function Wordmark({
  className,
  withMark = false,
}: {
  className?: string;
  withMark?: boolean;
}) {
  return (
    <span className={cn("inline-flex select-none items-center gap-2", className)}>
      {withMark && (
        <span
          aria-hidden
          className="grid h-5 w-5 shrink-0 place-items-center border border-accent-line bg-accent-soft"
        >
          <span className="h-1.5 w-1.5 bg-accent" />
        </span>
      )}
      <span className="text-[17px] font-semibold tracking-[var(--tracking-tightest)]">
        Metr
        <span className="text-accent">IQ</span>
      </span>
    </span>
  );
}

/* ---------------------------------------------------------- health status --- */

function HealthStatus() {
  const { data, error, loading } = useOnMount(api.health);

  const state = loading
    ? { color: "bg-ink-faint", label: "Connecting" }
    : error
      ? { color: "bg-fail", label: "API offline" }
      : data?.status === "ok"
        ? { color: "bg-pass", label: `API ${data.version}` }
        : { color: "bg-review", label: "Degraded" };

  return (
    <div
      className="flex items-center gap-2 border border-line-strong px-2 py-1"
      title={
        error
          ? "The MetrIQ backend is not reachable"
          : data
            ? `${data.service} · ${data.version}`
            : "Checking backend"
      }
    >
      <span
        className={cn(
          "inline-block h-1.5 w-1.5",
          state.color,
          loading && "animate-pulse",
        )}
      />
      <Mono muted className="text-[10px] uppercase tracking-[0.14em]">
        {state.label}
      </Mono>
    </div>
  );
}

/* ------------------------------------------------------------------ nav --- */

function NavItem({
  to,
  label,
  onClick,
}: {
  to: string;
  label: string;
  onClick?: () => void;
}) {
  return (
    <NavLink
      to={to}
      onClick={onClick}
      className={({ isActive }) =>
        cn(
          "group relative py-1 text-[13px] transition-colors",
          isActive ? "text-ink" : "text-ink-soft hover:text-ink",
        )
      }
    >
      {({ isActive }) => (
        <>
          {label}
          <span
            className={cn(
              "absolute -bottom-[21px] left-0 hidden h-[2px] w-full bg-accent transition-opacity md:block",
              isActive ? "opacity-100" : "opacity-0 group-hover:opacity-30",
            )}
          />
        </>
      )}
    </NavLink>
  );
}

function TopNav() {
  const [open, setOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-paper/85 backdrop-blur-md">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-accent/30" aria-hidden />
      <div className="mx-auto flex h-16 max-w-[1240px] items-center justify-between gap-6 px-5 sm:px-8">
        <div className="flex items-center gap-9">
          <NavLink to="/" className="flex items-center">
            <Wordmark withMark />
          </NavLink>
          <nav className="hidden items-center gap-7 md:flex">
            {NAV.map((item) => (
              <NavItem key={item.to} {...item} />
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-4">
          <HealthStatus />
          <button
            type="button"
            className="hidden text-ink-faint transition-colors hover:text-ink sm:block"
            aria-label="Settings"
            title="Settings"
          >
            <Settings className="h-4 w-4" />
          </button>
          <button
            type="button"
            className="text-ink md:hidden"
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>

      {open && (
        <nav className="border-t border-line bg-paper md:hidden">
          <div className="mx-auto flex max-w-[1240px] flex-col px-5 py-2 sm:px-8">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    "border-b border-line py-3 text-[14px] last:border-0",
                    isActive ? "text-accent" : "text-ink-soft",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </div>
        </nav>
      )}
    </header>
  );
}

/* ------------------------------------------------- system-layer footer --- */

export function SystemLayerFooter() {
  return (
    <footer className="mt-24 bg-accent text-white">
      <div className="relative overflow-hidden">
        {/* engineered grid + measurement ticks */}
        <div className="metriq-grid absolute inset-0" aria-hidden />
        <svg
          className="absolute inset-0 h-full w-full opacity-[0.5]"
          aria-hidden
          preserveAspectRatio="none"
        >
          <defs>
            <pattern
              id="ticks"
              width="176"
              height="176"
              patternUnits="userSpaceOnUse"
            >
              <path
                d="M0 8 H10 M0 88 H6 M88 0 V10 M88 88 V96"
                stroke="rgba(255,255,255,0.35)"
                strokeWidth="1"
              />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#ticks)" />
        </svg>

        <DigitHalftone className="right-2 max-h-[60%] w-[70%] opacity-70 [mask-image:linear-gradient(to_left,#000,transparent)]" />

        <div className="relative mx-auto max-w-[1240px] px-5 py-20 sm:px-8 sm:py-28">
          <div className="flex items-center gap-3">
            <span className="eyebrow !text-white/70">The MetrIQ system layer</span>
            <span className="h-px w-8 bg-white/40" aria-hidden />
          </div>
          <p className="display mt-5 max-w-xl text-[1.9rem] leading-[1.08] sm:text-[2.4rem]">
            Image to evidence to verified inspection report — every step recorded,
            every finding traceable to a source.
          </p>

          <div className="mt-14 grid gap-px border border-white/15 bg-white/15 sm:grid-cols-4">
            {[
              ["01", "Extraction", "OCR & declared-value capture"],
              ["02", "Standards", "Deterministic BIS retrieval"],
              ["03", "Rules", "Legal-metrology rule checks"],
              ["04", "Review", "Officer verification & sign-off"],
            ].map(([n, t, d]) => (
              <div key={n} className="bg-accent p-5">
                <Mono className="!text-white/50 text-[11px]">{n}</Mono>
                <div className="mt-2 text-[13px] font-semibold">{t}</div>
                <div className="mt-1 text-[12px] leading-snug text-white/60">
                  {d}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-16 flex flex-wrap items-end justify-between gap-6 border-t border-white/15 pt-8">
            <Wordmark className="text-white [&_span]:text-white" />
            <Mono className="!text-white/45 text-[11px]">
              AI-Assisted Legal Metrology Inspection · Prototype
            </Mono>
          </div>
        </div>
      </div>
    </footer>
  );
}

/* --------------------------------------------------------------- layout --- */

export function AppLayout() {
  return (
    <div className="flex min-h-dvh flex-col">
      <TopNav />
      <div className="relative mx-auto w-full max-w-[1240px] flex-1">
        <div className="content-rails pointer-events-none absolute inset-0 hidden lg:block" aria-hidden />
        <main className="px-5 py-12 sm:px-8 sm:py-16">
          <Outlet />
        </main>
      </div>
      <SystemLayerFooter />
      <ScrollRestoration />
    </div>
  );
}
