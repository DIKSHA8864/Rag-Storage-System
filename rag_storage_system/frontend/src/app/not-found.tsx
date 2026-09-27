import Link from "next/link";

export default function NotFound() {
  return (
    <div className="c-notfound">
      <p className="c-notfound-code">404</p>
      <h1>Page not found</h1>
      <p>The page you were looking for doesn&apos;t exist or has moved.</p>
      <Link href="/" className="c-cta">
        Go to the home page
      </Link>
    </div>
  );
}
