export function ErrorMessage({ message }: { message: string }) {
  return (
    <div
      role="alert"
      style={{
        padding: "0.75rem 1rem",
        border: "1px solid #c0392b",
        borderRadius: 4,
        color: "#c0392b",
        background: "#fdecea",
      }}
    >
      {message}
    </div>
  );
}