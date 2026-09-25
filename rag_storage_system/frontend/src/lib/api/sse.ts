import { ApiError } from "./client";

/**
 * Reads a Server-Sent Events response to the end, calling `onEvent` for
 * each "event:/data:" block as it arrives. Throws if the stream stops
 * without a final "done" event - a server-side failure cut it off, and
 * that must never read as an honest "no authority found".
 */
export async function readSseStream(
  response: Response,
  onEvent: (eventType: string, data: Record<string, unknown>) => void
): Promise<void> {
  if (!response.body) {
    throw new ApiError(0, "The server returned an empty response.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let sawDone = false;

  const handleBlock = (rawEvent: string) => {
    const lines = rawEvent.split("\n");
    const eventLine = lines.find((l) => l.startsWith("event: "));
    const dataLine = lines.find((l) => l.startsWith("data: "));
    if (!eventLine || !dataLine) return;

    const eventType = eventLine.slice("event: ".length);
    if (eventType === "done") sawDone = true;
    onEvent(eventType, JSON.parse(dataLine.slice("data: ".length)));
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    let separatorIndex = buffer.indexOf("\n\n");
    while (separatorIndex !== -1) {
      handleBlock(buffer.slice(0, separatorIndex));
      buffer = buffer.slice(separatorIndex + 2);
      separatorIndex = buffer.indexOf("\n\n");
    }
  }

  if (buffer.trim()) handleBlock(buffer);

  if (!sawDone) {
    throw new ApiError(0, "The answer was interrupted. Please try again.");
  }
}
