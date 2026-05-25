// "Print report" trigger that lives in each report tab's page-head actions
// slot. Inherits look from `.page-head .actions button` in home.css. Calling
// onClick fires the parent's `usePrintReport().print()` which expands every
// collapsed section in the report and then opens the native print dialog —
// users can pick "Save as PDF" to share with their team.

export function PrintReportButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      className="primary print-report-btn"
      onClick={onClick}
      title="Print report or save as PDF"
      aria-label="Print report or save as PDF"
      style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
    >
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M6 9V3h12v6" />
        <rect x="6" y="14" width="12" height="7" />
        <path d="M6 17H4a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2h-2" />
      </svg>
      <span>Print</span>
    </button>
  )
}
