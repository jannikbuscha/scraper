// Code-based routes of docs/UI.md §2. Search params are a flat string record,
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
import { NotFoundPage } from './pages/NotFoundPage';
import { OverviewPage } from './pages/OverviewPage';
import { RecentChangesPage } from './pages/RecentChangesPage';
import { RouteErrorPage } from './pages/RouteErrorPage';
import { TrashPage } from './pages/TrashPage';

/** Detail route component: remounts the page when the ID changes. */
function DetailRoute({ type }: { type: TableEntityType }) {
  const { id = '' } = useParams({ strict: false });
  return <EntityDetailPage key={id} type={type} id={id} />;
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
  route('/changes', RecentChangesPage),
  route('/comments', CommentsPage),
  route('/trash', TrashPage),
  route('/codebook', CodebookPage),
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
