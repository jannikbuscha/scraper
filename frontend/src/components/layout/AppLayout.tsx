// App shell (root route): header with brand, global search and navigation;
// provides the vocabulary index.
import { AppShell, Group } from '@mantine/core';
import { Link, Outlet } from '@tanstack/react-router';
import { useMemo } from 'react';

import { useVocab } from '../../api/queries';
import { VocabIndexContext } from '../../hooks/useVocabIndex';
import { buildVocabIndex } from '../../lib/vocab';
import { GlobalSearch } from './GlobalSearch';
import classes from './layout.module.css';
import { MainNav } from './MainNav';

/** Header height (two rows); sticky table headers sit just below it. */
export const HEADER_HEIGHT = 86;

export function AppLayout() {
  const vocab = useVocab();
  const vocabIndex = useMemo(() => buildVocabIndex(vocab.data?.vocabularies ?? []), [vocab.data]);

  return (
    <VocabIndexContext.Provider value={vocabIndex}>
      <a href="#main" className={classes.skipLink}>
        Skip to content
      </a>
      <AppShell header={{ height: HEADER_HEIGHT }} padding="md">
        <AppShell.Header>
          <Group className={classes.headerRow} justify="space-between" wrap="nowrap">
            <Link to="/" className={classes.brand}>
              MDT Portfolio
            </Link>
            <GlobalSearch />
          </Group>
          <MainNav />
        </AppShell.Header>
        <AppShell.Main id="main" tabIndex={-1} className={classes.main}>
          <Outlet />
        </AppShell.Main>
      </AppShell>
    </VocabIndexContext.Provider>
  );
}
