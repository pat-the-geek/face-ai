const OPTIONS = [
  { value: null, label: "TOUTES" },
  { value: "front", label: "FACE" },
  { value: "left", label: "PROFIL G." },
  { value: "right", label: "PROFIL D." },
];

export default function PoseFilter({ active, onChange }) {
  return (
    <div className="flex items-center gap-1 text-xs font-mono">
      {OPTIONS.map((opt) => (
        <button
          key={opt.value || "all"}
          onClick={() => onChange(opt.value)}
          className={`px-3 py-1 border divider transition-colors ${
            active === opt.value
              ? "border-accent text-accent"
              : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
