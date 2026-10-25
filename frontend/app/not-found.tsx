import Link from "next/link";

export default function NotFound() {
  return (
    <div className="card stack">
      <h1>Not found</h1>
      <p>This report or page doesn&apos;t exist. Check that the link was copied in full.</p>
      <Link href="/" className="btn btn-primary">Check a reel</Link>
    </div>
  );
}
