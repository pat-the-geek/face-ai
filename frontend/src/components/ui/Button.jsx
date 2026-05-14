export default function Button({
  active = false,
  danger = false,
  disabled = false,
  onClick,
  children,
  ...props
}) {
  const base =
    "px-3 py-1 border divider text-xs font-mono uppercase tracking-wider transition-colors disabled:opacity-40 disabled:cursor-not-allowed";
  const state =
    active || danger
      ? "border-accent text-accent"
      : "hover:border-accent hover:text-accent";
  return (
    <button
      className={`${base} ${state}`}
      disabled={disabled}
      onClick={onClick}
      {...props}
    >
      {children}
    </button>
  );
}
