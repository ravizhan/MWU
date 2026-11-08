interface Size {
  width: number
  height: number
}

interface Point {
  x: number
  y: number
}

/**
 * Map a point inside an `object-fit: contain` box to the intrinsic pixel grid.
 * Returns null for letterbox padding or when the intrinsic size is unknown.
 */
export function mapContainedPoint(point: Point, box: Size, natural: Size): Point | null {
  if (natural.width <= 0 || natural.height <= 0) return null
  const scale = Math.min(box.width / natural.width, box.height / natural.height)
  const offsetX = (box.width - natural.width * scale) / 2
  const offsetY = (box.height - natural.height * scale) / 2
  const x = Math.floor((point.x - offsetX) / scale)
  const y = Math.floor((point.y - offsetY) / scale)
  if (x < 0 || y < 0 || x >= natural.width || y >= natural.height) return null
  return { x, y }
}
