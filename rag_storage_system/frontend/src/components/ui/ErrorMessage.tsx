import { Icon } from "@/components/ui/Icon";

export function ErrorMessage({ message }: { message: string }) {
  return (
    <div
      role="alert"
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: "0.6rem",
        padding: "0.75rem 1rem",
        border: "1px solid #efc2bd",
        borderLeft: "4px solid #c0392b",
        borderRadius: 8,
        color: "#8e2a1f",
        background: "#fdf1ef",
        lineHeight: 1.5,
      }}
    >
      <span style={{ marginTop: "0.1rem", color: "#c0392b" }}>
        <Icon name="alert" />
      </span>
      <span>{message}</span>
    </div>
  );
}
