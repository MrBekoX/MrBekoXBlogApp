import { describe, expect, it } from 'vitest';
import { createChatChunkTracker, enqueueChatChunk } from '../chat-chunk-buffer';

describe('chat chunk buffer', () => {
  it('drops duplicate and lower sequence chunks after they were appended', () => {
    const first = enqueueChatChunk(createChatChunkTracker(), 0, 'Mer', false);
    const duplicate = enqueueChatChunk(first.tracker, 0, 'Mer', false);

    expect(first.appendText).toBe('Mer');
    expect(duplicate.dropped).toBe(true);
    expect(duplicate.appendText).toBe('');
  });

  it('buffers out-of-order chunks and flushes them when the gap closes', () => {
    const initial = createChatChunkTracker();
    const future = enqueueChatChunk(initial, 2, 'ya', true);
    const first = enqueueChatChunk(future.tracker, 0, 'Mer', false);
    const second = enqueueChatChunk(first.tracker, 1, 'ha', false);

    expect(future.appendText).toBe('');
    expect(first.appendText).toBe('Mer');
    expect(second.appendText).toBe('haya');
    expect(second.completed).toBe(true);
  });
});
