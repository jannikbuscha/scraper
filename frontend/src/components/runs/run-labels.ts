// Labels and colours of runs (docs/UI.md §8.3, docs/DATA_MODEL.md §14.2–§14.4).
import type { MantineColor } from '@mantine/core';

import type {
  FetchOutcome,
  MessageLevel,
  Run,
  RunStats,
  RunStatus,
  UnavailableReason,
} from '../../api/acquisition-types';
import { RUN_PARAMS, type RunParam } from '../../api/acquisition-types';
import type { JsonObject } from '../../api/types';
import { jsonText } from '../../lib/format';

export const RUN_STATUS_COLORS: Record<RunStatus, MantineColor> = {
  running: 'blue',
  succeeded: 'green',
  partial: 'orange',
  failed: 'red',
  cancelled: 'gray',
};

export const UNAVAILABLE_REASONS: Record<UnavailableReason, string> = {
  disabled: 'Disabled in sources.yaml',
  contact_email_missing: 'CONTACT_EMAIL is not set in .env',
};

export const unavailableText = (reason: UnavailableReason | null): string =>
  reason ? UNAVAILABLE_REASONS[reason] : 'Not available';

/** The `stats` counters in display order, with labels (docs/DATA_MODEL.md §14.2). */
export const STAT_LABELS: readonly [keyof Omit<RunStats, 'extra'>, string][] = [
  ['requests', 'Requests'],
  ['not_modified', 'Not modified (304)'],
  ['robots_disallowed', 'Disallowed by robots.txt'],
  ['bytes', 'Bytes received'],
  ['snapshots', 'Snapshots stored'],
  ['pages_parsed', 'Pages parsed'],
  ['parse_errors', 'Parse errors'],
  ['items_seen', 'Items seen'],
  ['entities_created', 'Records created'],
  ['entities_updated', 'Records updated'],
  ['revisions', 'Revisions'],
  ['proposals_opened', 'Proposals opened'],
  ['proposals_seen_again', 'Proposals seen again'],
  ['proposals_superseded', 'Proposals superseded'],
  ['observations_new', 'New observations'],
  ['observations_missing', 'Observations missing'],
  ['links_suggested', 'Links suggested'],
  ['messages_suppressed', 'Messages suppressed'],
  ['errors', 'Errors'],
  ['warnings', 'Warnings'],
];

export const MESSAGE_LEVEL_COLORS: Record<MessageLevel, MantineColor> = {
  error: 'red',
  warning: 'orange',
  info: 'blue',
};

export const FETCH_OUTCOME_COLORS: Record<FetchOutcome, MantineColor> = {
  ok: 'green',
  not_modified: 'teal',
  redirect: 'cyan',
  http_error: 'red',
  network_error: 'red',
  robots_disallowed: 'gray',
  blocked: 'red',
  too_large: 'orange',
  refused: 'orange',
};

export const PARAM_LABELS: Record<RunParam, string> = {
  limit: 'Limit (items)',
  refetch: 'Fetch known articles again',
  recall_sample: 'Recall sample size',
  recall_seed: 'Recall sample seed',
  document_ids: 'Documents',
};

const count = new Intl.NumberFormat('en-US');

export const formatCount = (value: number): string => count.format(value);

/** Bytes as B, kB, MB or GB (decimal units). */
export function formatBytes(bytes: number | null): string {
  if (bytes === null) return '—';
  if (bytes < 1000) return `${count.format(bytes)} B`;
  const units = ['kB', 'MB', 'GB', 'TB'];
  let value = bytes / 1000;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit] ?? ''}`;
}

/** A duration in seconds, e.g. `4.2 s`, `3 min 05 s`, `1 h 02 min`. */
export function formatDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return '—';
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ${String(Math.floor(seconds % 60)).padStart(2, '0')} s`;
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')} min`;
}

/** Whether the run answered from fixtures (`params.replay`, docs/COLLECTORS.md §4.10). */
export const isReplay = (run: Pick<Run, 'params'>): boolean => run.params.replay === true;

/** The run parameters a new run may repeat: the recorded ones without `replay`. */
export function repeatableParams(params: JsonObject): JsonObject {
  return Object.fromEntries(Object.entries(params).filter(([name]) => RUN_PARAMS.some((known) => known === name)));
}

/** `limit=5, refetch=true`, or `—`. */
export function formatParams(params: JsonObject): string {
  const entries = Object.entries(params).filter(([name]) => name !== 'replay');
  if (entries.length === 0) return '—';
  return entries
    .map(([name, value]) => `${name}=${Array.isArray(value) ? value.map((entry) => jsonText(entry)).join(' ') : jsonText(value)}`)
    .join(', ');
}
