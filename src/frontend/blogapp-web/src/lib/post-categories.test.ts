import { describe, expect, it } from 'vitest';
import { postCategories } from './post-categories';

const dotnet = { id: '1', name: '.NET', slug: 'dotnet' };

describe('postCategories', () => {
  it('reads the singular category returned by the API', () => {
    expect(postCategories({ category: dotnet })).toEqual([dotnet]);
  });

  it('keeps an existing categories array', () => {
    expect(postCategories({ categories: [dotnet], category: null })).toEqual([dotnet]);
  });

  it('returns nothing when the post has no category', () => {
    expect(postCategories({})).toEqual([]);
  });
});
