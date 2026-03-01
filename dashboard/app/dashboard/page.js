import { notFound } from "next/navigation";
import Link from "next/link";
import LevelRing from "@/components/LevelRing";
import XPBar from "@/components/XPBar";
import QuestCard from "@/components/QuestCard";
import ActivityHeatmap from "@/components/ActivityHeatmap";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ??
  "https://game-of-claude-production.up.railway.app";

async function fetchProfile(deviceId) {
  const res = await fetch(`${API_BASE}/api/profile/${deviceId}`, {
    next: { revalidate: 30 },
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("Failed to load profile");
  return res.json();
}

async function fetchActivity(deviceId) {
  try {
    const res = await fetch(`${API_BASE}/api/activity/${deviceId}`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) return {};
    const data = await res.json();
    return data.activity ?? {};
  } catch {
    return {};
  }
}

export async function generateMetadata({ searchParams }) {
  const id = (await searchParams).id;
  if (!id) return { title: "Game of Claude" };
  try {
    const profile = await fetchProfile(id);
    if (!profile) return { title: "Profile not found — Game of Claude" };
    return {
      title: `${profile.character_name} · Lvl ${profile.level} ${profile.level_title}`,
      description: `${profile.total_xp.toLocaleString()} XP · ${profile.current_streak}d streak · ${profile.total_commits} commits`,
    };
  } catch {
    return { title: "Game of Claude" };
  }
}

export default async function DashboardPage({ searchParams }) {
  const id = (await searchParams).id;
  if (!id) return <MissingId />;

  const [profile, activity] = await Promise.all([
    fetchProfile(id),
    fetchActivity(id),
  ]);

  if (!profile) notFound();

  const dailyQuests = profile.quests.filter((q) => q.type === "daily");
  const progressiveQuests = profile.quests.filter(
    (q) => q.type === "progressive" && !q.completed
  );
  const completedProgressiveQuests = profile.quests.filter(
    (q) => q.type === "progressive" && q.completed
  );

  return (
    <main className="min-h-screen bg-surface px-4 py-10 max-w-2xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-4 mb-8">
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-white">{profile.character_name}</h1>
          <p className="text-sm text-muted mt-0.5">
            Member since{" "}
            {new Date(profile.member_since).toLocaleDateString("en-US", {
              month: "long",
              year: "numeric",
            })}
          </p>
        </div>
        <div className="text-right">
          <div className="text-2xl font-bold text-gold">{profile.total_xp.toLocaleString()}</div>
          <div className="text-xs text-muted uppercase tracking-wide">Total XP</div>
        </div>
      </div>

      {/* Level ring + XP bar */}
      <div className="bg-card border border-border rounded-2xl p-6 mb-6 flex flex-col items-center gap-6">
        <LevelRing
          level={profile.level}
          xpInLevel={profile.xp_in_level}
          xpToNextLevel={profile.xp_to_next_level}
          levelTitle={profile.level_title}
        />
        <div className="w-full max-w-sm">
          <XPBar
            xpInLevel={profile.xp_in_level}
            xpToNextLevel={profile.xp_to_next_level}
          />
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-3 mb-6">
        <StatCard label="Commits" value={profile.total_commits} />
        <StatCard label="Tests passed" value={profile.total_test_passes} />
        <StatCard label="Sessions" value={profile.total_sessions} />
        <StatCard
          label="Current streak"
          value={`${profile.current_streak}d`}
          accent
        />
        <StatCard label="Longest streak" value={`${profile.longest_streak}d`} />
        <Link
          href="/leaderboard"
          className="bg-card border border-border hover:border-brand/50 rounded-xl p-3 text-center transition-colors"
        >
          <div className="text-xl font-bold text-brand-light">↗</div>
          <div className="text-xs text-muted mt-0.5">Leaderboard</div>
        </Link>
      </div>

      {/* Daily quests */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">
          Daily Quests
        </h2>
        <div className="flex flex-col gap-2">
          {dailyQuests.map((q) => (
            <QuestCard key={q.id} quest={q} />
          ))}
        </div>
      </section>

      {/* Active progressive quests */}
      {progressiveQuests.length > 0 && (
        <section className="mb-6">
          <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">
            Active Quests
          </h2>
          <div className="flex flex-col gap-2">
            {progressiveQuests.map((q) => (
              <QuestCard key={q.id} quest={q} />
            ))}
          </div>
        </section>
      )}

      {/* Activity heatmap */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">
          Activity
        </h2>
        <div className="bg-card border border-border rounded-2xl p-4">
          <ActivityHeatmap activity={activity} />
        </div>
      </section>

      {/* Completed quests */}
      {completedProgressiveQuests.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">
            Completed
          </h2>
          <div className="flex flex-col gap-2 opacity-60">
            {completedProgressiveQuests.map((q) => (
              <QuestCard key={q.id} quest={q} />
            ))}
          </div>
        </section>
      )}
    </main>
  );
}

function StatCard({ label, value, accent }) {
  return (
    <div className="bg-card border border-border rounded-xl p-3 text-center">
      <div
        className={`text-xl font-bold ${accent ? "text-gold" : "text-white"}`}
      >
        {value}
      </div>
      <div className="text-xs text-muted mt-0.5">{label}</div>
    </div>
  );
}

function MissingId() {
  return (
    <main className="min-h-screen bg-surface flex items-center justify-center px-4">
      <div className="text-center max-w-sm">
        <div className="text-4xl mb-4">🎮</div>
        <h1 className="text-xl font-bold text-white mb-2">No profile ID</h1>
        <p className="text-muted text-sm mb-4">
          Add <code className="text-brand-light">?id=your-device-id</code> to
          the URL, or{" "}
          <Link href="/install" className="text-brand-light underline">
            install game-of-claude
          </Link>{" "}
          to get yours.
        </p>
      </div>
    </main>
  );
}
