// The generic record page `/records/$id` (docs/UI.md §2): records without a
// table (evidence, participations, components, relations, indicators, saved
// views) get the same detail page as the table types, with fields, edit,
// delete and undelete, history (compare, restore) and comments. The type
// comes from the ID prefix. Table types and vocabulary terms are redirected to
// their own pages, keeping the search parameters (e.g. a comment thread).
import { Navigate } from '@tanstack/react-router';

import { ErrorAlert } from '../components/feedback';
import { useUrlSearch } from '../hooks/useUrlSearch';
import { DETAIL_PATHS, isRecordPageType, isTableType, typeFromId } from '../lib/entity';
import { EntityDetailPage } from './EntityDetailPage';

export function RecordPage({ id }: { id: string }) {
  const [search] = useUrlSearch();
  const type = typeFromId(id);
  if (isTableType(type)) return <Navigate to={DETAIL_PATHS[type]} params={{ id }} search={search} replace />;
  if (type === 'vocabulary_term') return <Navigate to="/codebook" search={{ ...search, term: id }} replace />;
  if (isRecordPageType(type)) return <EntityDetailPage type={type} id={id} />;
  return (
    <ErrorAlert
      title="Record not found"
      error={new Error(`“${id}” is not the ID of a record that has a page of its own.`)}
    />
  );
}
