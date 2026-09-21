/**
 * Scroll-driven motion, written against the platform rather than a library —
 * IntersectionObserver plus one transform write per frame. No dependency, no
 * per-frame React render.
 *
 * Every hook here is a PROGRESSIVE ENHANCEMENT. Under `prefers-reduced-motion`,
 * or where IntersectionObserver is missing, content starts in its final state:
 * nothing is ever left hidden because an effect did not run.
 */
import { useEffect, useRef, useState } from "react";

function reducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches)
  );
}

function canObserve(): boolean {
  return typeof IntersectionObserver !== "undefined";
}

/** True once the element has been seen. Never flips back, so content read
 *  during a fast scroll stays put. */
export function useReveal<T extends HTMLElement>(threshold = 0.12) {
  const ref = useRef<T | null>(null);
  const [shown, setShown] = useState(() => reducedMotion() || !canObserve());

  useEffect(() => {
    const node = ref.current;
    if (!node || reducedMotion() || !canObserve()) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShown(true);
          io.disconnect();
        }
      },
      { threshold, rootMargin: "0px 0px -6% 0px" },
    );
    io.observe(node);
    return () => io.disconnect();
  }, [threshold]);

  return { ref, shown };
}

/**
 * Slow vertical drift for artwork. `strength` is the total travel in px across
 * one screen of scrolling — keep it small: this should be felt, not seen.
 * Only runs while the element is near the viewport.
 */
export function useParallax<T extends HTMLElement>(strength = 40) {
  const ref = useRef<T | null>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node || reducedMotion() || !canObserve()) return;

    let near = false;
    let frame = 0;

    const apply = () => {
      frame = 0;
      const el = ref.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      // -1 below the fold .. +1 above it, 0 when vertically centred.
      const progress =
        (window.innerHeight / 2 - (r.top + r.height / 2)) / window.innerHeight;
      el.style.transform = `translate3d(0, ${(progress * strength).toFixed(2)}px, 0)`;
    };

    const onScroll = () => {
      if (!near || frame) return;
      frame = requestAnimationFrame(apply);
    };

    const io = new IntersectionObserver(
      ([entry]) => {
        near = entry.isIntersecting;
        if (near) apply();
      },
      { rootMargin: "240px 0px" },
    );
    io.observe(node);
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    return () => {
      io.disconnect();
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [strength]);

  return ref;
}

/**
 * Which step of a sequence the reader is on, from scroll position across a tall
 * section. Returns the index and the ref to attach to the scrolling container.
 * Used by the "how it works" stepper so the stage follows the reader rather
 * than animating on a timer.
 */
export function useScrollStep<T extends HTMLElement>(steps: number) {
  const ref = useRef<T | null>(null);
  const [step, setStep] = useState(0);

  useEffect(() => {
    const node = ref.current;
    if (!node || steps < 2) return;

    let frame = 0;
    const measure = () => {
      frame = 0;
      const el = ref.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const travel = r.height - window.innerHeight;
      if (travel <= 0) return;
      const progress = Math.min(Math.max(-r.top / travel, 0), 0.999);
      const next = Math.floor(progress * steps);
      // Only publish a real change: this runs on every scroll frame.
      setStep((prev) => (prev === next ? prev : next));
    };
    const onScroll = () => {
      if (frame) return;
      frame = requestAnimationFrame(measure);
    };

    measure();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [steps]);

  return { ref, step, setStep };
}
