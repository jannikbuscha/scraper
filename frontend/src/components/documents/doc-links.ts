// Document links in the app (docs/UI.md §8.7, docs/DATA_MODEL.md §15.8): each
// action sends the full `links` list in which only that link changed. A
// suggested link is confirmed or rejected; automatic links are never removed
// (a rejected one stays, so its subject is not suggested again); manual links
// can be removed; an added link is a confirmed manual link.
import type { DocLink, JsonObject, JsonValue } from '../../api/types';
import { asNumber, asString, asStringArray, isJsonObject } from '../../lib/format';

export type LinkAction = 'confirm' | 'reject' | 'remove';

const STATES: readonly DocLink['state'][] = ['suggested', 'confirmed', 'rejected'];

/** The links of a document (`fields.links`). */
export function asDocLinks(value: JsonValue | undefined): DocLink[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isJsonObject).flatMap((entry) => {
    const subjectId = asString(entry.subject_id ?? null);
    const state = STATES.find((candidate) => candidate === entry.state);
    if (!subjectId || !state) return [];
    return [
      {
        subject_id: subjectId,
        origin: entry.origin === 'auto' ? 'auto' : 'manual',
        state,
        matched_aliases: asStringArray(entry.matched_aliases),
        match_count: asNumber(entry.match_count ?? null),
        snippet: asString(entry.snippet ?? null),
      },
    ];
  });
}

/** The actions a link offers. */
export function linkActions(link: Pick<DocLink, 'origin' | 'state'>): LinkAction[] {
  if (link.origin === 'manual') return link.state === 'confirmed' ? ['remove'] : ['confirm', 'remove'];
  if (link.state === 'suggested') return ['confirm', 'reject'];
  return link.state === 'confirmed' ? ['reject'] : ['confirm'];
}

const toJson = (link: DocLink): JsonObject => ({
  subject_id: link.subject_id,
  origin: link.origin,
  state: link.state,
  matched_aliases: link.matched_aliases ?? [],
  match_count: link.match_count ?? null,
  snippet: link.snippet ?? null,
});

/** The full list after `action` on the link of `subjectId`; every other link unchanged. */
export function linksAfter(links: readonly DocLink[], subjectId: string, action: LinkAction): JsonObject[] {
  if (action === 'remove') {
    return links.filter((link) => !(link.subject_id === subjectId && link.origin === 'manual')).map(toJson);
  }
  const state = action === 'confirm' ? 'confirmed' : 'rejected';
  return links.map((link) => toJson(link.subject_id === subjectId ? { ...link, state } : link));
}

/** The full list with a confirmed manual link added; null if the subject is linked already. */
export function linksWithAdded(links: readonly DocLink[], subjectId: string): JsonObject[] | null {
  if (links.some((link) => link.subject_id === subjectId)) return null;
  return [...links.map(toJson), { subject_id: subjectId, origin: 'manual', state: 'confirmed' }];
}
