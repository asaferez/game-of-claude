"use client";
import { useEffect, useRef } from "react";

const SIZE = 160;
const STROKE = 12;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export default function LevelRing({ level, xpInLevel, xpToNextLevel, levelTitle }) {
  const progress = xpToNextLevel > 0 ? Math.min(xpInLevel / xpToNextLevel, 1) : 0;
  const offset = CIRCUMFERENCE * (1 - progress);
  const circleRef = useRef(null);

  useEffect(() => {
    if (!circleRef.current) return;
    circleRef.current.style.setProperty("--circumference", CIRCUMFERENCE);
    circleRef.current.style.setProperty("--offset", offset);
    // Trigger animation by resetting then setting
    circleRef.current.style.strokeDashoffset = CIRCUMFERENCE;
    requestAnimationFrame(() => {
      circleRef.current.style.transition = "stroke-dashoffset 1s ease-out";
      circleRef.current.style.strokeDashoffset = offset;
    });
  }, [offset]);

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative" style={{ width: SIZE, height: SIZE }}>
        <svg width={SIZE} height={SIZE} className="-rotate-90">
          {/* Track */}
          <circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            fill="none"
            stroke="#2a2a3e"
            strokeWidth={STROKE}
          />
          {/* Fill */}
          <circle
            ref={circleRef}
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            fill="none"
            stroke="#8b5cf6"
            strokeWidth={STROKE}
            strokeLinecap="round"
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={CIRCUMFERENCE}
          />
        </svg>
        {/* Center text */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-4xl font-bold text-white">{level}</span>
          <span className="text-xs text-muted uppercase tracking-wider">Level</span>
        </div>
      </div>
      <div className="text-center">
        <div className="text-sm font-medium text-brand-light">{levelTitle}</div>
        <div className="text-xs text-muted mt-0.5">
          {xpInLevel} / {xpToNextLevel} XP
        </div>
      </div>
    </div>
  );
}
