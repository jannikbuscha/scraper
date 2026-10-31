// Main navigation (docs/UI.md §2, §8.1). "Review (n)" shows the open proposals
// from /api/stats (polled every 60 s and refetched after writes; hidden when
// 0); "Runs" shows a small spinner while a collector run is running.
// Later-phase pages are not listed yet.
import { Loader, VisuallyHidden } from '@mantine/core';
import { Link } from '@tanstack/react-router';

import { useStats } from '../../api/queries';
import classes from './layout.module.css';

const ITEMS = [
  { to: '/', label: 'Overview' },
  { to: '/projects', label: 'Projects' },
  { to: '/services', label: 'Services' },
  { to: '/events', label: 'Events' },
  { to: '/documents', label: 'Documents' },
  { to: '/organizations', label: 'Organizations' },
  { to: '/review', label: 'Review' },
  { to: '/changes', label: 'Changes' },
  { to: '/comments', label: 'Comments' },
  { to: '/runs', label: 'Runs' },
  { to: '/sources', label: 'Sources' },
  { to: '/import', label: 'Import' },
  { to: '/codebook', label: 'Codebook' },
  { to: '/trash', label: 'Trash' },
] as const;

/** The review count is polled every minute (docs/UI.md §8.1). */
export const STATS_POLL_MS = 60_000;

export function MainNav() {
  const stats = useStats({ refetchInterval: STATS_POLL_MS });
  const openProposals = stats.data?.open_proposals ?? 0;
  const running = stats.data?.runs.running ?? null;
  return (
    <nav aria-label="Main" className={classes.nav}>
      {ITEMS.map((item) => (
        <Link
          key={item.to}
          to={item.to}
          className={classes.navLink}
          activeOptions={{ exact: item.to === '/', includeSearch: false }}
        >
          {item.label}
          {item.to === '/review' && openProposals > 0 && ` (${openProposals})`}
          {item.to === '/runs' && running && (
            <>
              <Loader size={10} ml={6} aria-hidden />
              <VisuallyHidden> (a run is running)</VisuallyHidden>
            </>
          )}
        </Link>
      ))}
    </nav>
  );
}
