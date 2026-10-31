// A link to a record known only by its ID (a decision's `result_id`, a merged
// record's `merged_into`): labelled from the lookup (docs/API.md §3.1), like
// every record link (docs/UI.md §3); the ID shows until the label has loaded.
import { useLookupIds } from '../api/lookup';
import { EntityLink } from './EntityLink';

export function LookupEntityLink({ id }: { id: string }) {
  const found = useLookupIds([id]).byId.get(id);
  return <EntityLink id={id} label={found?.label} type={found?.type} deleted={found?.deleted} />;
}
