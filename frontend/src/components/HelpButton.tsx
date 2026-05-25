// Bottom-right help icon that replays the guided tour. Always rendered
// (in every mode) so a returning visitor who skipped the auto-tour can
// pull it up on demand. Uses an inline SVG help-circle to match the
// rest of the site's icon language (thin stroke, currentColor, no text
// glyphs).

interface HelpButtonProps {
  onClick: () => void
}

export function HelpButton({ onClick }: HelpButtonProps) {
  return (
    <button
      type="button"
      className="help-button"
      onClick={onClick}
      aria-label="Replay guided tour"
      title="Replay guided tour"
    >
      <svg
        width="22"
        height="22"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="10" />
        <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
        <path d="M12 17h.01" />
      </svg>
    </button>
  )
}
