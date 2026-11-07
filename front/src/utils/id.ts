// crypto.randomUUID 只在安全上下文可用，局域网 HTTP 访问时不存在；getRandomValues 不受此限制
export function createId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("")
}
