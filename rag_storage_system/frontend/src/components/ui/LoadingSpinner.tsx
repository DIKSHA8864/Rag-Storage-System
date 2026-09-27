export function LoadingSpinner({ label = "Loading..." }: { label?: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      style={{ padding: "2.5rem 1rem", display: "flex", alignItems: "center", justifyContent: "center", gap: "0.7rem", color: "#5a6573" }}
    >
      {/* The as-spin keyframes live in components/layout/console.css, which is always loaded. */}
      <span
        aria-hidden
        style={{
          width: 20,
          height: 20,
          borderRadius: "50%",
          border: "2.5px solid #d6dde5",
          borderTopColor: "#1f4e79",
          animation: "as-spin 0.8s linear infinite",
        }}
      />
      <span>{label}</span>
    </div>
  );
}
