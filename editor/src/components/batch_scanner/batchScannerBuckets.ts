/**
 * Batch scanner completion-date buckets.
 *
 * Separates completed ScannerRecords by the UI device's local calendar day so
 * the live board stays focused on today's results while older results remain accessible.
 */
import type { ScannerRecord } from '@/api/scanner'

export interface FinishedScannerBuckets {
  today: ScannerRecord[]
  history: ScannerRecord[]
}

/** Return a stable local-date key without converting the calendar day to UTC. */
export function localDateKey(value: Date): string {
  return `${value.getFullYear()}-${value.getMonth()}-${value.getDate()}`
}

/** Partition completed records into today's local results and prior history. */
export function partitionFinishedScans(records: ScannerRecord[], now = new Date()): FinishedScannerBuckets {
  const todayKey = localDateKey(now)
  const result: FinishedScannerBuckets = { today: [], history: [] }
  for (const record of records) {
    if (record.status !== 'finished') continue
    const finishedAt = new Date(record.finished_at || record.updated_at)
    if (!Number.isNaN(finishedAt.getTime()) && localDateKey(finishedAt) === todayKey) result.today.push(record)
    else result.history.push(record)
  }
  return result
}
