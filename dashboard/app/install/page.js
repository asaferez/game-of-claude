"use client";
import { useState } from "react";

const INSTALL_CMD = "npx game-of-claude install";

export default function InstallPage() {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    await navigator.clipboard.writeText(INSTALL_CMD);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <main className="min-h-screen bg-surface flex flex-col items-center justify-center px-4 py-12">
      <div className="max-w-lg w-full text-center">
        {/* Logo / title */}
        <div className="text-5xl mb-4">🎮</div>
        <h1 className="text-3xl font-bold text-white mb-2">Game of Claude</h1>
        <p className="text-muted mb-8 leading-relaxed">
          Level up while you ship real work. Get XP for commits, passing tests,
          and daily streaks — never for token count or prompt volume.
        </p>

        {/* Install command */}
        <div className="bg-card border border-border rounded-xl p-4 mb-6 text-left">
          <p className="text-xs text-muted uppercase tracking-wider mb-2">
            Run in your terminal
          </p>
          <div className="flex items-center justify-between gap-3">
            <code className="text-brand-light font-mono text-sm break-all">
              {INSTALL_CMD}
            </code>
            <button
              onClick={handleCopy}
              className="shrink-0 text-xs px-3 py-1.5 rounded-lg border border-border hover:border-brand/50 text-muted hover:text-white transition-colors"
            >
              {copied ? "Copied!" : "Copy"}
            </button>
          </div>
        </div>

        {/* Steps */}
        <div className="text-left mb-8">
          <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-4">
            What happens
          </h2>
          <ol className="space-y-3">
            {[
              ["Pick a character name", "Your identity in the game. No email required."],
              ["Get a device ID", "A random UUID — no account, no PII."],
              ["Hooks are installed", "Claude Code hooks are written to ~/.claude/settings.json automatically."],
              ["Start coding", "XP flows as you work. View your dashboard at the URL you receive."],
            ].map(([title, desc], i) => (
              <li key={i} className="flex gap-3">
                <span className="shrink-0 w-6 h-6 rounded-full bg-brand/20 text-brand-light text-xs flex items-center justify-center font-bold mt-0.5">
                  {i + 1}
                </span>
                <div>
                  <div className="text-sm font-medium text-white">{title}</div>
                  <div className="text-xs text-muted mt-0.5">{desc}</div>
                </div>
              </li>
            ))}
          </ol>
        </div>

        {/* What earns XP */}
        <div className="bg-card border border-border rounded-xl p-4 mb-8 text-left">
          <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">
            What earns XP
          </h2>
          <div className="space-y-2">
            {[
              ["Git commit", "+15 XP"],
              ["Test passed", "+8 XP"],
              ["Session with a commit", "+20 XP"],
              ["Daily streak (day N)", "+10×N XP"],
              ["Quest completion", "varies"],
            ].map(([action, xp]) => (
              <div key={action} className="flex justify-between text-sm">
                <span className="text-gray-300">{action}</span>
                <span className="text-gold font-medium">{xp}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Privacy note */}
        <p className="text-xs text-muted">
          No PII stored. Stop tracking anytime:{" "}
          <code className="text-gray-400">game-of-claude stop</code>. Delete
          all data:{" "}
          <code className="text-gray-400">game-of-claude delete-data</code>.
        </p>
      </div>
    </main>
  );
}
