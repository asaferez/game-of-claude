import Link from "next/link";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ??
  "https://game-of-claude-production.up.railway.app";

export const metadata = {
  title: "Leaderboard — Game of Claude",
  description: "Top players ranked by total XP earned while shipping real work.",
};

async function fetchLeaderboard() {
  try {
    const res = await fetch(`${API_BASE}/api/leaderboard`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) return [];
    const data = await res.json();
    return data.leaderboard ?? [];
  } catch {
    return [];
  }
}

export default async function LeaderboardPage({ searchParams }) {
  const myId = (await searchParams).id;
  const rows = await fetchLeaderboard();

  return (
    <main className="min-h-screen bg-surface px-4 py-10 max-w-2xl mx-auto">
      <div className="flex items-center gap-3 mb-8">
        <Link href="/" className="text-muted hover:text-white text-sm transition-colors">
          ← Home
        </Link>
        <h1 className="text-2xl font-bold text-white mx-auto">Leaderboard</h1>
        <span className="text-muted text-sm">Top 20</span>
      </div>

      {rows.length === 0 ? (
        <div className="text-center text-muted py-20">
          <div className="text-4xl mb-4">🏆</div>
          <p>No players yet. Be the first!</p>
          <Link href="/install" className="text-brand-light underline mt-2 inline-block">
            Install now
          </Link>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {rows.map((row, i) => (
            <Link
              key={row.device_id}
              href={`/dashboard?id=${row.device_id}`}
              className={`bg-card border rounded-xl p-4 flex items-center gap-4 hover:border-brand/50 transition-colors ${
                row.device_id === myId ? "border-brand" : "border-border"
              }`}
            >
              <span
                className={`w-8 text-center font-bold text-lg shrink-0 ${
                  i === 0
                    ? "text-gold"
                    : i === 1
                    ? "text-gray-300"
                    : i === 2
                    ? "text-amber-600"
                    : "text-muted"
                }`}
              >
                {i + 1}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-white font-semibold truncate">
                  {row.character_name}
                </div>
                <div className="text-xs text-brand-light">{row.level_title}</div>
              </div>
              <div className="text-right shrink-0">
                <div className="text-gold font-bold">
                  {row.total_xp.toLocaleString()}
                </div>
                <div className="text-xs text-muted">XP · Lvl {row.level}</div>
              </div>
              {row.current_streak > 0 && (
                <div className="text-xs text-muted whitespace-nowrap shrink-0">
                  🔥 {row.current_streak}d
                </div>
              )}
            </Link>
          ))}
        </div>
      )}

      <p className="text-xs text-muted text-center mt-8">
        <Link href="/install" className="underline hover:text-white">
          Install game-of-claude
        </Link>{" "}
        to appear on the leaderboard.
      </p>
    </main>
  );
}
