// Link to an entity's detail page, labelled in <bdi> and struck through if
// deleted. Types without a detail page render the label as text.
import type { RecordType } from '../api/types';
import { DETAIL_PATHS, isTableType, typeFromId } from '../lib/entity';
import type { SearchRecord } from '../lib/query-string';
import { AnchorLink } from './AnchorLink';

interface EntityLinkProps {
  id: string;
  label?: string | null | undefined;
  /** Defaults to the type encoded in the ID prefix. */
  type?: RecordType | null | undefined;
  deleted?: boolean | undefined;
  /** Detail-page search params, e.g. `{comments: 'open', thread: id}`. */
  search?: SearchRecord | undefined;
}

export function EntityLink({ id, label, type, deleted = false, search }: EntityLinkProps) {
  const resolved = type ?? typeFromId(id);
  const text = <bdi>{label ?? id}</bdi>;
  const content = deleted ? <s title="deleted">{text}</s> : text;
  if (!isTableType(resolved)) return content;
  return (
    <AnchorLink to={DETAIL_PATHS[resolved]} params={{ id }} search={search ?? {}} c={deleted ? 'dimmed' : undefined}>
      {content}
    </AnchorLink>
  );
}
