import { formatINR } from '../app/formatters'
import type { ReconciliationRow, RunSummary } from '../app/types'

export function SummaryStrip({ run, rows }: { run: RunSummary; rows: ReconciliationRow[] }) {
  const exceptions = rows.filter((row) => row.exception_type).length
  const refused = rows.filter((row) => row.decision === 'REFUSED').length
  const coverage = run.expected_paise ? (run.explained_paise / run.expected_paise) * 100 : 0
  const boundedCoverage = Math.min(100, Math.max(0, coverage))
  const items = [
    { label: 'Expected', value: formatINR(run.expected_paise) },
    { label: 'Explained', value: formatINR(run.explained_paise) },
    { label: 'Coverage', value: `${coverage.toFixed(1)}%`, coverage: true },
    { label: 'Exceptions', value: String(exceptions) },
    { label: 'Refused', value: String(refused) },
  ]
  return (
    <dl className="summary-strip">
      {items.map((item) => (
        <div key={item.label} className={item.coverage ? 'coverage-summary' : undefined}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
          {item.coverage && (
            <span
              className="coverage-track"
              role="progressbar"
              aria-label="Explained money coverage"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Number(coverage.toFixed(1))}
            >
              <span style={{ width: `${boundedCoverage}%` }} />
            </span>
          )}
        </div>
      ))}
    </dl>
  )
}
