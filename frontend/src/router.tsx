// Code-based routes of docs/UI.md §2 and §8.1. Search params are a flat string record,
// serialised exactly as docs/UI.md §1.2 prescribes.
import { createRootRoute, createRoute, createRouter, useParams } from '@tanstack/react-router';
import type { ReactElement } from 'react';

import type { TableEntityType } from './api/types';
import { AppLayout } from './components/layout/AppLayout';
import { parseSearch, stringifySearch, validateSearch } from './lib/query-string';
import { CodebookPage } from './pages/CodebookPage';
import { CommentsPage } from './pages/CommentsPage';
import { EntityDetailPage } from './pages/EntityDetailPage';
import { EntityTablePage } from './pages/EntityTablePage';
import { ImportPage } from './pages/ImportPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { OverviewPage } from './pages/OverviewPage';
import { RecentChangesPage } from './pages/RecentChangesPage';
import { RecordPage } from './pages/RecordPage';
import { ReviewPage } from './pages/ReviewPage';
import { RouteErrorPage } from './pages/RouteErrorPage';
import { RunDetailPage } from './pages/RunDetailPage';
import { RunsPage } from './pages/RunsPage';
import { SourceDetailPage } from './pages/SourceDetailPage';
import { SourcesPage } from './pages/SourcesPage';
import { TrashPage } from './pages/TrashPage';

/** Detail route component: remounts the page when the ID changes. */
function DetailRoute({ type }: { type: TableEntityType }) {
  const { id = '' } = useParams({ strict: false });
  return <EntityDetailPage key={id} type={type} id={id} />;
}

/** The generic record page: remounts when the ID changes. */
function RecordRoute() {
  const { id = '' } = useParams({ strict: false });
  return <RecordPage key={id} id={id} />;
}

/** A run's page: remounts when the ID changes (e.g. after "Run again"). */
function RunRoute() {
  const { id = '' } = useParams({ strict: false });
  return <RunDetailPage key={id} />;
}

/** A collector's page: remounts when the collector changes. */
function SourceRoute() {
  const { collector = '' } = useParams({ strict: false });
  return <SourceDetailPage key={collector} />;
}

// One component per route; React Fast Refresh and the hooks lint rules need
// statically declared components.
const ProjectsPage = () => <EntityTablePage type="project" />;
const ServicesPage = () => <EntityTablePage type="service" />;
const EventsPage = () => <EntityTablePage type="event" />;
const DocumentsPage = () => <EntityTablePage type="document" />;
const OrganizationsPage = () => <EntityTablePage type="organization" />;
const ProjectPage = () => <DetailRoute type="project" />;
const ServicePage = () => <DetailRoute type="service" />;
const EventPage = () => <DetailRoute type="event" />;
const DocumentPage = () => <DetailRoute type="document" />;
const OrganizationPage = () => <DetailRoute type="organization" />;

// validateSearch on the root passes every key through to all routes.
const rootRoute = createRootRoute({
  component: AppLayout,
  validateSearch,
  notFoundComponent: NotFoundPage,
  errorComponent: RouteErrorPage,
});

const route = <P extends string>(path: P, component: () => ReactElement) =>
  createRoute({ getParentRoute: () => rootRoute, path, component });

const routeTree = rootRoute.addChildren([
  route('/', OverviewPage),
  route('/projects', ProjectsPage),
  route('/projects/$id', ProjectPage),
  route('/services', ServicesPage),
  route('/services/$id', ServicePage),
  route('/events', EventsPage),
  route('/events/$id', EventPage),
  route('/documents', DocumentsPage),
  route('/documents/$id', DocumentPage),
  route('/organizations', OrganizationsPage),
  route('/organizations/$id', OrganizationPage),
  route('/records/$id', RecordRoute),
  route('/changes', RecentChangesPage),
  route('/comments', CommentsPage),
  route('/trash', TrashPage),
  route('/codebook', CodebookPage),
  // Phase 2 (docs/UI.md §8.1)
  route('/review', ReviewPage),
  route('/runs', RunsPage),
  route('/runs/$id', RunRoute),
  route('/sources', SourcesPage),
  route('/sources/$collector', SourceRoute),
  route('/import', ImportPage),
]);

export const router = createRouter({
  routeTree,
  parseSearch,
  stringifySearch,
  defaultPreload: false,
  scrollRestoration: true,
});

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}
