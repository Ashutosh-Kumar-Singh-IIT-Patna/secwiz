"use client";

interface StepperProps {
  current: 1 | 2 | 3;
  steps: string[];
}

export function Stepper({ current, steps }: StepperProps) {
  return (
    <ol className="mb-8 grid grid-cols-3 gap-3 text-xs">
      {steps.map((label, i) => {
        const idx = (i + 1) as 1 | 2 | 3;
        const state =
          idx < current ? "done" : idx === current ? "active" : "future";
        return (
          <li
            key={label}
            className={[
              "flex items-center gap-2 rounded-md border px-3 py-2",
              state === "active"
                ? "border-emerald-500/50 bg-emerald-500/5 text-emerald-200"
                : state === "done"
                  ? "border-ink-700 bg-ink-800/40 text-ink-300"
                  : "border-ink-800 bg-ink-800/20 text-ink-400",
            ].join(" ")}
          >
            <span
              className={[
                "flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold",
                state === "active"
                  ? "bg-emerald-500 text-ink-900"
                  : state === "done"
                    ? "bg-emerald-500/30 text-emerald-200"
                    : "bg-ink-700 text-ink-300",
              ].join(" ")}
            >
              {state === "done" ? "✓" : idx}
            </span>
            <span className="truncate text-sm">{label}</span>
          </li>
        );
      })}
    </ol>
  );
}
