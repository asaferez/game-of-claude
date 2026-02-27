export default function QuestCard({ quest }) {
  const { name, description, type, goal, current, completed, xp_reward } = quest;
  const progress = goal > 0 ? Math.min((current / goal) * 100, 100) : 0;

  return (
    <div
      className={`rounded-xl border p-4 ${
        completed
          ? "border-brand/50 bg-brand/10"
          : "border-border bg-card"
      }`}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-white">{name}</span>
            {completed && (
              <span className="text-xs bg-brand/30 text-brand-light px-1.5 py-0.5 rounded-full">
                Done
              </span>
            )}
            <span
              className={`text-xs px-1.5 py-0.5 rounded-full ${
                type === "daily"
                  ? "bg-amber-900/40 text-amber-400"
                  : "bg-sky-900/40 text-sky-400"
              }`}
            >
              {type === "daily" ? "Daily" : "Quest"}
            </span>
          </div>
          <p className="text-xs text-muted mt-0.5">{description}</p>
        </div>
        <div className="text-right shrink-0">
          <span className="text-sm font-bold text-gold">+{xp_reward}</span>
          <div className="text-xs text-muted">XP</div>
        </div>
      </div>
      <div className="mt-2">
        <div className="flex justify-between text-xs text-muted mb-1">
          <span>
            {current} / {goal}
          </span>
          <span>{Math.round(progress)}%</span>
        </div>
        <div className="h-1.5 bg-border rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-700 ${
              completed
                ? "bg-brand-light"
                : "bg-gradient-to-r from-brand to-brand-light"
            }`}
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>
    </div>
  );
}
