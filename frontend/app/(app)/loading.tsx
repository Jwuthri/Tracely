// Shown while an authed page's server data is fetching (instead of a frozen blank screen).
export default function DashboardLoading() {
  return (
    <div className="space-y-6" aria-busy="true">
      <div className="space-y-2">
        <div className="h-7 w-52 animate-pulse rounded-md bg-white/[0.06]" />
        <div className="h-4 w-96 max-w-full animate-pulse rounded bg-white/[0.04]" />
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-24 animate-pulse rounded-xl border border-line bg-white/[0.02]" />
        ))}
      </div>
      <div className="space-y-2.5">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-12 animate-pulse rounded-lg border border-line bg-white/[0.02]" />
        ))}
      </div>
    </div>
  );
}
