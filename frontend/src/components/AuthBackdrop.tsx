"use client";

/**
 * The sign-in hero: HMAP's hierarchy as three floating plates in CSS 3D space. Your goal enters on the top plate (you
 * and the Manager), is broken down on the middle plate (Analyst, Planner) and handed to the specialists on the bottom
 * plate. Task blocks fall through the layers; the stack tilts toward the pointer. Decorative (aria-hidden); still under
 * prefers-reduced-motion.
 */
import { useEffect, useRef, type CSSProperties } from "react";

interface Plate {
  z: number;
  title: string;
  seats: string[];
  top?: boolean;
}

const GAP = 118;
const PLATES: Plate[] = [
  { z: 0, title: "Specialists", seats: ["Researcher", "Developer", "Tester", "Writer", "Reviewer"] },
  { z: GAP, title: "Planning", seats: ["Analyst", "Planner"] },
  { z: GAP * 2, title: "Your goal", seats: ["You", "Manager"], top: true },
];

// blocks fall from the top plate, pause on the middle one, land on a specialist
const DROPS = [
  { x: 36, y: 132, delay: "0s" },
  { x: 150, y: 150, delay: "-2s" },
  { x: 236, y: 132, delay: "-4s" },
];

function PlateView({ plate }: { plate: Plate }) {
  return (
    <div className={plate.top ? "hm-plate hm-plate-top" : "hm-plate"} style={{ transform: `translateZ(${plate.z}px)` }}>
      <div className="flex h-full flex-col p-4">
        <p className={plate.top ? "font-display text-[15px] font-semibold text-on-accent" : "font-display text-[15px] font-semibold text-fg"}>
          {plate.title}
        </p>
        <div className="mt-auto flex flex-wrap gap-1.5">
          {plate.seats.map((s) => (
            <span key={s} className="hm-seat px-2 py-1 text-[11px] font-medium text-fg">
              {s}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

export function HierarchyStack() {
  const stage = useRef<HTMLDivElement>(null);
  const stack = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = stage.current;
    const target = stack.current;
    if (!el || !target || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const onMove = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      const dx = (e.clientX - (r.left + r.width / 2)) / r.width;   // -0.5 … 0.5
      const dy = (e.clientY - (r.top + r.height / 2)) / r.height;
      target.style.setProperty("--hm-tilt-z", `${-38 + dx * 14}deg`);
      target.style.setProperty("--hm-tilt-x", `${58 - dy * 10}deg`);
    };
    const onLeave = () => {
      target.style.removeProperty("--hm-tilt-z");
      target.style.removeProperty("--hm-tilt-x");
    };
    window.addEventListener("pointermove", onMove);
    document.addEventListener("pointerleave", onLeave);
    return () => {
      window.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerleave", onLeave);
    };
  }, []);

  return (
    <div ref={stage} aria-hidden="true" className="hm-stage relative mx-auto mt-6 h-[460px] w-full max-w-[540px] select-none">
      <div className="absolute top-[70%] left-1/2 h-[220px] w-[300px] -translate-x-1/2 -translate-y-1/2">
        <div ref={stack} className="hm-stack relative h-full w-full">
          {/* floor shadow */}
          <div className="absolute inset-[-12%] rounded-[40px] bg-[radial-gradient(closest-side,rgb(var(--hm-shadow)/0.28),transparent)] blur-md" style={{ transform: "translateZ(-30px)" }} />
          {PLATES.map((p) => (
            <PlateView key={p.title} plate={p} />
          ))}
          {DROPS.map((d) => (
            <div
              key={d.x}
              className="hm-drop absolute size-5 rounded-[6px] bg-accent shadow-[0_3px_0_var(--hm-accent-edge)]"
              style={{ left: d.x, top: d.y, animationDelay: d.delay, "--from": `${GAP * 2 + 40}px`, "--mid": `${GAP + 14}px`, "--to": "14px" } as CSSProperties}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

/** The desk under the sign-in page: a binder spine on the left edge (the grain comes from body::before). */
export function AuthBackdrop() {
  return <div aria-hidden="true" className="hm-spine pointer-events-none fixed inset-y-0 left-0 -z-10 w-8" />;
}
