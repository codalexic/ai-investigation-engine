export async function parseSSE(stream, onEvent) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = '', type = 'message', data = [];
  function line(value) {
    if (!value) {
      if (data.length) onEvent(type, JSON.parse(data.join('\n')));
      type = 'message'; data = [];
      return;
    }
    if (value.startsWith(':')) return;
    const colon = value.indexOf(':');
    const field = colon < 0 ? value : value.slice(0, colon);
    let content = colon < 0 ? '' : value.slice(colon + 1);
    if (content.startsWith(' ')) content = content.slice(1);
    if (field === 'event') type = content;
    if (field === 'data') data.push(content);
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let match;
      while ((match = /\r\n|\r|\n/.exec(buffer))) {
        if (!done && match[0] === '\r' && match.index === buffer.length - 1) break;
        line(buffer.slice(0, match.index));
        buffer = buffer.slice(match.index + match[0].length);
      }
      if (done) break;
    }
  } finally {
    await reader.cancel();
    reader.releaseLock();
  }
}
