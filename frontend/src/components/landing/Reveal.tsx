"use client";
import { useEffect, useRef, useState } from "react";

export function Reveal({
  children, delay = 0, as: Tag = "div", className = "",
}: { children: React.ReactNode; delay?: number; as?: React.ElementType; className?: string }) {
  const ref = useRef<HTMLElement>(null);
  // Initialize deterministically so the server and client first render agree
  // (data-shown undefined). shouldSkipAnimation() returns true on the server
  // — no IntersectionObserver — but false on the client, which previously
  // produced a `data-shown` hydration mismatch. Decide skip-vs-observe after
  // mount; reduced-motion users are shown immediately by CSS (.reveal rule).
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      el.dataset.shown = ""; // no observer (ancient browser): reveal immediately
      return;
    }
    const io = new IntersectionObserver((entries) => {
      const e = entries[0]; if (!e) return;
      if (e.isIntersecting) { setShown(true); io.disconnect(); }
    }, { threshold: 0.14 });
    io.observe(el); return () => io.disconnect();
  }, []);
  return (
    <Tag ref={ref} data-shown={shown ? "" : undefined}
      style={{ transitionDelay: `${delay}ms` }}
      className={`reveal ${className}`}>{children}</Tag>
  );
}

export function CountUp({ to, suffix = "" }: { to: number; suffix?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    if (typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches) return; // final value already in DOM
    if (typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver((entries) => {
      const e = entries[0]; if (!e || !e.isIntersecting) return; io.disconnect();
      const start = performance.now(), dur = 1200;
      const tick = (now: number) => {
        const p = Math.min(1, (now - start) / dur), k = 1 - Math.pow(1 - p, 3);
        el.textContent = Math.round(to * k).toLocaleString() + suffix;
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }, { threshold: 0.5 });
    io.observe(el); return () => io.disconnect();
  }, [to, suffix]);
  return <span ref={ref} className="tabular-nums">{to.toLocaleString()}{suffix}</span>;
}
