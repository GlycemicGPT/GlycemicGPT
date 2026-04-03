/**
 * LTTB (Largest-Triangle-Three-Buckets) downsampling algorithm.
 *
 * Reduces a time-series dataset to a target number of points while
 * preserving visual shape. Used for rendering long glucose histories
 * (e.g., 30 days = ~8640 points) without overloading Recharts.
 *
 * Reference: Sveinn Steinarsson (2013), "Downsampling Time Series for
 * Visual Representation"
 */

export interface TimeSeriesPoint {
  timestamp: number;
  value: number;
}

/**
 * Downsample a sorted time-series array using LTTB.
 *
 * @param data  - Array sorted by timestamp (ascending)
 * @param target - Desired number of output points (must be >= 2)
 * @returns Downsampled array of the same type
 *
 * If the data length is <= target, the original array is returned as-is.
 *
 * Note: LTTB selects points that maximize triangle area, which naturally
 * preserves spikes and valleys. However, it does not explicitly guarantee
 * that threshold-crossing points (e.g., glucose crossing from in-range
 * to urgent-high) are retained. For clinical displays, pair with a
 * reasonable target (500+ points) to minimize information loss.
 *
 * Edge case: if multiple readings share the same timestamp (duplicate
 * syncs), triangle areas degenerate to zero and the algorithm falls
 * back to selecting the first point in each bucket.
 */
export function lttbDownsample<T extends TimeSeriesPoint>(
  data: T[],
  target: number,
): T[] {
  if (target >= data.length || target < 2) return data;

  const sampled: T[] = [];
  const bucketSize = (data.length - 2) / (target - 2);

  // Always keep the first point
  sampled.push(data[0]);

  let prevIndex = 0;

  for (let i = 1; i < target - 1; i++) {
    // Calculate the bucket boundaries
    const bucketStart = Math.floor((i - 1) * bucketSize) + 1;
    const bucketEnd = Math.min(
      Math.floor(i * bucketSize) + 1,
      data.length - 2, // exclude last point (added separately)
    );

    // Calculate the average point of the next bucket (for triangle area)
    const nextBucketStart = Math.floor(i * bucketSize) + 1;
    const nextBucketEnd = Math.min(
      Math.floor((i + 1) * bucketSize) + 1,
      data.length - 1,
    );

    let avgX = 0;
    let avgY = 0;
    const nextBucketLen = nextBucketEnd - nextBucketStart + 1;
    for (let j = nextBucketStart; j <= nextBucketEnd; j++) {
      avgX += data[j].timestamp;
      avgY += data[j].value;
    }
    avgX /= nextBucketLen;
    avgY /= nextBucketLen;

    // Pick the point in the current bucket that forms the largest triangle
    // with the previously selected point and the next bucket's average
    const prevX = data[prevIndex].timestamp;
    const prevY = data[prevIndex].value;

    let maxArea = -1;
    let maxAreaIndex = bucketStart;

    for (let j = bucketStart; j <= bucketEnd; j++) {
      // Triangle area (doubled, we only need relative comparison)
      const area = Math.abs(
        (prevX - avgX) * (data[j].value - prevY) -
        (prevX - data[j].timestamp) * (avgY - prevY),
      );
      if (area > maxArea) {
        maxArea = area;
        maxAreaIndex = j;
      }
    }

    sampled.push(data[maxAreaIndex]);
    prevIndex = maxAreaIndex;
  }

  // Always keep the last point
  sampled.push(data[data.length - 1]);

  return sampled;
}
