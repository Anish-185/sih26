import { useEffect, useState } from "react";
import {
  NavLink,
  Outlet,
  ScrollRestoration,
  useLocation,
} from "react-router-dom";
import { Menu, X } from "lucide-react";
import { api } from "@/lib/api";
import { useOnMount } from "@/lib/hooks";
import { cn } from "@/lib/cn";
import { LinkButton, Mono } from "@/components/ui";
import { BrailleField } from "@/components/decor";

/* The bar carries the surfaces in the order the product is meant to be read:
   ask a question, find the standard for a product, then the services around it.
   The camera is one way into that story, not a seventh peer link, so it stays a
   button. */
const NAV = [
  { to: "/ask", label: "Ask" },
  { to: "/standards", label: "Standards" },
  { to: "/inspection", label: "Inspection" },
  { to: "/certification", label: "Certification" },
  { to: "/laboratories", label: "Labs" },
  { to: "/hallmarking", label: "Hallmarking" },
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
              "absolute -bottom-[23px] left-0 hidden h-[2px] w-full bg-accent transition-opacity lg:block",
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
      <div className="mx-auto flex h-[68px] max-w-[1240px] items-center justify-between gap-6 px-5 sm:px-8">
        <div className="flex items-center gap-10">
          <NavLink to="/" className="flex items-center" aria-label="MetrIQ home">
            <Wordmark withMark />
          </NavLink>
          <nav className="hidden items-center gap-7 lg:flex">
            {NAV.map((item) => (
              <NavItem key={item.to} {...item} />
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-3">
          <HealthStatus />
          <LinkButton to="/standards" size="sm" className="hidden sm:inline-flex">
            Find a standard
          </LinkButton>
          <button
            type="button"
            className="text-ink lg:hidden"
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>

      {open && (
        <nav className="border-t border-line bg-paper lg:hidden">
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
            <LinkButton to="/standards" size="sm" className="mt-4 mb-2 self-start sm:hidden">
              Find a standard
            </LinkButton>
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

        <BrailleField
          tone="white"
          rows={16}
          cols={64}
          className="bottom-0 right-0 leading-[13px] [mask-image:linear-gradient(to_left,#000,transparent_82%)]"
        />

        <div className="relative mx-auto max-w-[1240px] px-5 py-20 sm:px-8 sm:py-28">
          <div className="flex items-center gap-3">
            <span className="eyebrow !text-white/70">The MetrIQ evidence layer</span>
            <span className="h-px w-8 bg-white/40" aria-hidden />
          </div>
          <p className="display mt-5 max-w-xl text-[1.9rem] leading-[1.08] sm:text-[2.4rem]">
            A question — or a photograph — to the Indian Standard that governs the
            product, and the official BIS page it came from.
          </p>

          <div className="mt-14 grid gap-px border border-white/15 bg-white/15 sm:grid-cols-4">
            {[
              ["01", "Question", "Plain words, a photograph, or both"],
              ["02", "Retrieval", "Deterministic search over verified BIS records"],
              ["03", "Standard", "The Indian Standard, its route and its labs"],
              ["04", "Evidence", "Every step traceable to an official source"],
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
              Indian Standards & BIS Services · Evidence-backed · Prototype
            </Mono>
          </div>
        </div>
      </div>
    </footer>
  );
}

/* --------------------------------------------------------------- layout --- */

export function AppLayout() {
  // Full-bleed bands are sized from 100vw, which includes the scrollbar gutter.
  // Publishing its real width keeps them exactly as wide as the viewport.
  useEffect(() => {
    const set = () =>
      document.documentElement.style.setProperty(
        "--scrollbar",
        `${window.innerWidth - document.documentElement.clientWidth}px`,
      );
    set();
    window.addEventListener("resize", set);
    return () => window.removeEventListener("resize", set);
  }, []);

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
