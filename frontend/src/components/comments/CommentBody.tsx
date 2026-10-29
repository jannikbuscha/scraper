// Comment text: the server-rendered, server-sanitised `body_html`, passed
// through DOMPurify again with the server's allowlist (docs/UI.md §1.4). This
// is the only place in the app that injects HTML.
import { Typography } from '@mantine/core';

import { sanitizeCommentHtml } from '../../lib/sanitize';
import classes from './comments.module.css';

export function CommentBody({ html }: { html: string }) {
  return (
    <Typography className={classes.body}>
      {/* eslint-disable-next-line react/no-danger -- the one allowed exception: sanitised by the server (nh3) and again here (DOMPurify) */}
      <div dangerouslySetInnerHTML={{ __html: sanitizeCommentHtml(html) }} />
    </Typography>
  );
}
