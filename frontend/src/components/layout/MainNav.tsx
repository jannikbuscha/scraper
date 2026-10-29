// Main navigation (docs/UI.md §2). Later-phase pages are not listed yet.
import { Link } from '@tanstack/react-router';

import classes from './layout.module.css';

const ITEMS = [
  { to: '/', label: 'Overview' },
  { to: '/projects', label: 'Projects' },
  { to: '/services', label: 'Services' },
  { to: '/events', label: 'Events' },
  { to: '/documents', label: 'Documents' },
  { to: '/organizations', label: 'Organizations' },
  { to: '/changes', label: 'Changes' },
  { to: '/comments', label: 'Comments' },
  { to: '/codebook', label: 'Codebook' },
  { to: '/trash', label: 'Trash' },
] as const;

export function MainNav() {
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
        </Link>
      ))}
    </nav>
  );
}
