export function LoadingSpinner({ label = "Loading..." }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" style={{ padding: "2rem", textAlign: "center" }}>
      <span>{label}</span>
    </div>
  );
}