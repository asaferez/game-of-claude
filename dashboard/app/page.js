import Link from "next/link";

export const metadata = {
  title: "Game of Claude — Level up while you ship",
  description:
    "Gamification layer for Claude Code. Get XP for commits, passing tests, and daily streaks — rewarded for real output, never for token count.",
};

export default function Home() {
  return (
    <main className="min-h-screen bg-surface flex flex-col items-center justify-center px-4 py-12">
      <div className="max-w-lg w-full text-center">
        <div className="text-5xl mb-4">🎮</div>
        <h1 className="text-3xl font-bold text-white mb-2">Game of Claude</h1>
        <p className="text-muted mb-10 leading-relaxed text-lg">
          Level up while you ship real work. XP for commits, passing tests,
          and daily streaks — never for prompt volume.
        </p>

        {/* Static profile preview */}
        <div className="bg-card border border-border rounded-2xl p-5 mb-8 text-left">
          <div className="flex items-center gap-4 mb-4">
            <div className="w-14 h-14 rounded-full bg-brand/20 border-2 border-brand flex items-center justify-center text-white font-bold text-xl">
              7
            </div>
            <div>
              <div className="text-white font-semibold">ByteKnight</div>
              <div className="text-sm text-brand-light">Context Crafter</div>
            </div>
            <div className="ml-auto text-right">
              <div className="text-gold font-bold text-xl">2,450</div>
              <div className="text-xs text-muted">Total XP</div>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2 text-center">
            {[
              ["47", "Commits"],
              ["23", "Tests"],
              ["🔥 12d", "Streak"],
            ].map(([v, l]) => (
              <div key={l} className="bg-surface rounded-lg p-2">
                <div className="text-white font-bold text-sm">{v}</div>
                <div className="text-xs text-muted">{l}</div>
              </div>
            ))}
          </div>
        </div>

        {/* CTAs */}
        <div className="flex flex-col sm:flex-row gap-3">
          <Link
            href="/install"
            className="flex-1 bg-brand hover:bg-brand-dark text-white font-semibold py-3 rounded-xl transition-colors"
          >
            Install now
          </Link>
          <Link
            href="/leaderboard"
            className="flex-1 border border-border hover:border-brand/50 text-muted hover:text-white font-semibold py-3 rounded-xl transition-colors"
          >
            View leaderboard
          </Link>
        </div>
      </div>
    </main>
  );
}
