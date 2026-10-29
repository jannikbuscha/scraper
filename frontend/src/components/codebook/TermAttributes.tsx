// A term's `attributes` (e.g. candidate, fixed, counts_as_modification,
// paper_basis) as small badges: true flags by name, other values as
// "name: value"; false flags are left out.
import { Badge, Tooltip } from '@mantine/core';

import type { JsonValue } from '../../api/types';
import { jsonText } from '../../lib/format';
import classes from './codebook.module.css';
import { attributesOf } from './term-form';

const words = (key: string): string => key.replace(/_/g, ' ');

export function TermAttributes({ attributes }: { attributes: JsonValue | undefined }) {
  const entries = Object.entries(attributesOf(attributes)).filter(([, value]) => value !== false && value !== null);
  if (entries.length === 0) return null;
  return (
    <span className={classes.badges}>
      {entries.map(([key, value]) => {
        const text = value === true ? words(key) : `${words(key)}: ${jsonText(value)}`;
        return (
          <Tooltip key={key} label={`attributes.${key} = ${JSON.stringify(value)}`}>
            <Badge size="xs" variant="light" color={key === 'fixed' ? 'grape' : 'gray'} className={classes.attribute}>
              <bdi>{text}</bdi>
            </Badge>
          </Tooltip>
        );
      })}
    </span>
  );
}
