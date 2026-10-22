import { describe, expect, it } from 'vitest';
import { getTabLabel } from './ide-tab-label';

describe('getTabLabel', () => {
  it('mevcut rotalar korunur', () => {
    expect(getTabLabel('/')).toBe('how-to-center.md');
    expect(getTabLabel('/posts')).toBe('posts-list.md');
    expect(getTabLabel('/posts/vim-shortcuts')).toBe('vim-shortcuts.md');
    expect(getTabLabel('/unknown')).toBe('index.md');
  });

  it('/about kendi sekme etiketini alır', () => {
    expect(getTabLabel('/about')).toBe('about.md');
  });
});
