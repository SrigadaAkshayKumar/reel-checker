export default function Loading() {
  return (
    <div className="stack" aria-busy="true" aria-label="Loading the report">
      <div className="card">
        <div className="skeleton" style={{ height: 14, width: 120 }} />
        <div className="skeleton" style={{ height: 40, width: 220, marginTop: 10 }} />
        <div className="skeleton" style={{ height: 16, marginTop: 12 }} />
      </div>
      <div className="card skeleton" style={{ height: 140 }} />
      <div className="card skeleton" style={{ height: 200 }} />
    </div>
  );
}
