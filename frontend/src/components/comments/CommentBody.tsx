// Comment text: the `body_html` the server renders from the Markdown body
// (raw HTML disabled, docs/API.md §3.3).
import { Typography } from '@mantine/core';

import classes from './comments.module.css';

export function CommentBody({ html }: { html: string }) {
  return (
    <Typography className={classes.body}>
      <div dangerouslySetInnerHTML={{ __html: html }} />
    </Typography>
  );
}
