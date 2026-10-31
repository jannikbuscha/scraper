// Every `stats` counter of a run, labelled, and the collector-specific
// `extra` counters as given (docs/UI.md §8.3).
import { Title } from '@mantine/core';

import type { RunStats } from '../../api/acquisition-types';
import { jsonText } from '../../lib/format';
import { formatBytes, formatCount, STAT_LABELS } from './run-labels';
import classes from './runs.module.css';

export function StatsGrid({ stats }: { stats: RunStats }) {
  const extra = Object.entries(stats.extra);
  return (
    <section aria-labelledby="run-stats">
      <Title order={2} id="run-stats" mb="xs">
        Statistics
      </Title>
      <dl className={classes.stats}>
        {STAT_LABELS.map(([key, label]) => (
          <div key={key} className={classes.stat}>
            <dt>{label}</dt>
            <dd>{key === 'bytes' ? formatBytes(stats[key]) : formatCount(stats[key])}</dd>
          </div>
        ))}
        {extra.map(([key, value]) => (
          <div key={`extra.${key}`} className={classes.stat}>
            <dt>{key}</dt>
            <dd>{typeof value === 'number' ? formatCount(value) : jsonText(value)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
