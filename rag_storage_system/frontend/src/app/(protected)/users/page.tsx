import { UserManager } from "@/components/users/UserManager";

export default function UsersPage() {
  return (
    <div style={{ maxWidth: 820, margin: "0 auto" }}>
      <h1>Users</h1>
      <p style={{ color: "#666", fontSize: "0.9rem" }}>
        Invite the people who use AshiLegal. They sign up once at <strong>/portal/signup</strong> with the invited
        email (a 6-digit code confirms it&apos;s theirs), then sign in with their own password. They can only Ask
        questions and complete their own Intake - never see or change the library. Deactivating someone signs them
        out everywhere, immediately.
      </p>
      <div style={{ marginTop: "1.5rem" }}>
        <UserManager />
      </div>
    </div>
  );
}
