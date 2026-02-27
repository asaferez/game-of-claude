"use client";
import { useEffect, useRef } from "react";

export default function XPBar({ xpInLevel, xpToNextLevel }) {
  const barRef = useRef(null);
  const progress = xpToNextLevel > 0 ? Math.min((xpInLevel / xpToNextLevel) * 100, 100) : 0;

  useEffect(() => {
    if (!barRef.current) return;
    barRef.current.style.width = "0%";
    requestAnimationFrame(() => {
      barRef.current.style.transition = "width 1s ease-out";
      barRef.current.style.width = `${progress}%`;
    });
  }, [progress]);

  return (
    <div className="w-full">
      <div className="flex justify-between text-xs text-muted mb-1">
        <span>{xpInLevel} XP</span>
        <span>{xpToNextLevel} XP to next level</span>
      </div>
      <div className="h-2 bg-border rounded-full overflow-hidden">
        <div
          ref={barRef}
          className="h-full rounded-full"
          style={{
            width: "0%",
            background: "linear-gradient(90deg, #6d28d9, #8b5cf6)",
          }}
        />
      </div>
    </div>
  );
}
