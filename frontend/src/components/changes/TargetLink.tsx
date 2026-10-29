// A link to a record's place in the UI (targets.ts); without a target the
// label is plain text. Labels are data and are wrapped in <bdi>.
import type { ReactNode } from 'react';

import { useEntity } from '../../api/queries';
import type { TableEntityType } from '../../api/types';
import { DETAIL_PATHS, RECORD_PATH, TABLE_PATHS } from '../../lib/entity';
import { asString } from '../../lib/format';
import { searchFromQuery } from '../../lib/query-string';
import { AnchorLink } from '../AnchorLink';
import type { RecordTarget } from './targets';

/** A saved view opens as its table with the stored query applied (once the view is loaded). */
function SavedViewLink({ id, tableType, children }: { id: string; tableType: TableEntityType; children: ReactNode }) {
  const view = useEntity('saved_view', id);
  const query = asString(view.data?.item.fields.query ?? null);
  if (query === null) return <>{children}</>;
  return (
    <AnchorLink to={TABLE_PATHS[tableType]} search={searchFromQuery(query)}>
      {children}
    </AnchorLink>
  );
}

export function TargetLink({ target, label }: { target: RecordTarget | null; label: string }) {
  const text = <bdi>{label}</bdi>;
  if (target === null) return text;
  switch (target.kind) {
    case 'detail':
      return (
        <AnchorLink to={DETAIL_PATHS[target.type]} params={{ id: target.id }} search={target.search}>
          {text}
        </AnchorLink>
      );
    case 'record':
      return (
        <AnchorLink to={RECORD_PATH} params={{ id: target.id }} search={target.search}>
          {text}
        </AnchorLink>
      );
    case 'codebook':
      return (
        <AnchorLink to="/codebook" search={target.search}>
          {text}
        </AnchorLink>
      );
    case 'saved_view':
      return (
        <SavedViewLink id={target.id} tableType={target.tableType}>
          {text}
        </SavedViewLink>
      );
  }
}
