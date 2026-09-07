export async function readBoundedBytes(response: Response, maximumBytes: number): Promise<Uint8Array<ArrayBuffer>> {
  if (!Number.isInteger(maximumBytes) || maximumBytes < 1) {
    throw new Error("The JSON byte limit is invalid.");
  }

  const declared = response.headers.get("Content-Length");
  if (declared !== null) {
    const normalized = declared.trim();
    if (!/^\d+$/.test(normalized) || Number(normalized) > maximumBytes) {
      throw new Error("The JSON response exceeds its public size limit.");
    }
  }

  if (!response.body) {
    throw new Error("The JSON response body is unavailable.");
  }

  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > maximumBytes) {
        await reader.cancel("Response exceeds its public size limit.");
        throw new Error("The JSON response exceeds its public size limit.");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

export async function readBoundedJson(response: Response, maximumBytes: number): Promise<unknown> {
  const bytes = await readBoundedBytes(response, maximumBytes);
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown;
}
