export interface BufferedChatChunk {
  chunk: string;
  isFinal: boolean;
}

export interface ChatChunkTracker {
  nextSequence: number;
  bufferedChunks: Record<number, BufferedChatChunk>;
  completed: boolean;
}

export interface ChatChunkEnqueueResult {
  tracker: ChatChunkTracker;
  appendText: string;
  dropped: boolean;
  completed: boolean;
}

export function createChatChunkTracker(): ChatChunkTracker {
  return {
    nextSequence: 0,
    bufferedChunks: {},
    completed: false,
  };
}

export function enqueueChatChunk(
  current: ChatChunkTracker | undefined,
  sequence: number,
  chunk: string,
  isFinal: boolean,
): ChatChunkEnqueueResult {
  const tracker: ChatChunkTracker = current
    ? {
        nextSequence: current.nextSequence,
        bufferedChunks: { ...current.bufferedChunks },
        completed: current.completed,
      }
    : createChatChunkTracker();

  if (tracker.completed || sequence < tracker.nextSequence) {
    return {
      tracker,
      appendText: '',
      dropped: true,
      completed: tracker.completed,
    };
  }

  if (sequence > tracker.nextSequence) {
    if (!tracker.bufferedChunks[sequence]) {
      tracker.bufferedChunks[sequence] = { chunk, isFinal };
    }

    return {
      tracker,
      appendText: '',
      dropped: false,
      completed: tracker.completed,
    };
  }

  let appendText = '';
  let completed = false;
  let currentSequence = sequence;
  let currentChunk: BufferedChatChunk | undefined = { chunk, isFinal };

  while (currentChunk) {
    appendText += currentChunk.chunk;
    completed = completed || currentChunk.isFinal;
    tracker.nextSequence = currentSequence + 1;

    if (currentChunk.isFinal) {
      tracker.completed = true;
      tracker.bufferedChunks = {};
      break;
    }

    currentSequence = tracker.nextSequence;
    const buffered = tracker.bufferedChunks[currentSequence];
    if (!buffered) {
      break;
    }

    delete tracker.bufferedChunks[currentSequence];
    currentChunk = buffered;
  }

  return {
    tracker,
    appendText,
    dropped: false,
    completed,
  };
}

export function completeChatChunkTracker(current: ChatChunkTracker | undefined): ChatChunkTracker {
  return {
    ...(current ?? createChatChunkTracker()),
    bufferedChunks: {},
    completed: true,
  };
}
