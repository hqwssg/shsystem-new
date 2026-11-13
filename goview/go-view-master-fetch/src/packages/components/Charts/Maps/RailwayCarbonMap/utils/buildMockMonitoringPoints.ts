import type { AccountingPoint, LineFeature, MonitoringPoint } from '../types'
import { DEFAULT_STATION_ORDER } from '../types'
import { findPositionOnPolyline, polylineLengthKm, sampleAlongPolyline, slicePolylineBetween } from './routeGeometry'

/** 站间每 3 公里至少一个点，且不少于 5 个（不含两端车站） */
export function interiorPointCount(segmentKm: number): number {
  if (segmentKm <= 0) return 0
  return Math.max(5, Math.ceil(segmentKm / 3))
}

function mockCarbonIntensity(chainageKm: number, direction: 'up' | 'down'): number {
  const base = 6 + 3.5 * Math.sin(chainageKm / 35) + 1.2 * Math.sin(chainageKm / 8)
  const value = direction === 'down' ? base * 0.78 + 0.6 * Math.sin(chainageKm / 18) : base
  return Math.round(Math.max(value, 0.1) * 10) / 10
}

function mockEnergyIntensity(chainageKm: number, direction: 'up' | 'down'): number {
  const base = 22 + 6 * Math.sin(chainageKm / 48)
  const value = direction === 'down' ? base * 0.8 : base
  return Math.round(Math.max(value, 0.1) * 10) / 10
}

/**
 * 沿上行折线、从神池南累计里程，在相邻站之间均匀放置模拟核算点。
 * 上行和下行共用这条折线位置，强度各自模拟。里程单位为公里。
 * 每个点隶属更近的车站，正中间归上游站。
 */
export function buildMockMonitoringPoints(
  stations: AccountingPoint[],
  parentLines: LineFeature[],
  stationOrder: string[] = DEFAULT_STATION_ORDER
): MonitoringPoint[] {
  const result: MonitoringPoint[] = []
  const find = (name: string) => stations.find(s => s.name === name)
  const parentUp = parentLines.find(f => f.properties.direction === 'up')
  if (!parentUp) return result

  const upCoords = parentUp.geometry.coordinates as [number, number][]

  for (let i = 0; i < stationOrder.length - 1; i++) {
    const fromName = stationOrder[i]
    const toName = stationOrder[i + 1]
    const from = find(fromName)
    const to = find(toName)
    if (!from || !to) continue

    const segCoords = slicePolylineBetween(upCoords, from, to)
    const segmentKm = polylineLengthKm(segCoords)
    const count = interiorPointCount(segmentKm)
    if (count < 2) continue

    const segmentStartKm = findPositionOnPolyline(upCoords, {
      lng: segCoords[0][0],
      lat: segCoords[0][1]
    }).distanceKm
    const end = segCoords[segCoords.length - 1]
    const samples = [
      { lng: segCoords[0][0], lat: segCoords[0][1], chainageKm: 0 },
      ...sampleAlongPolyline(segCoords, count, false),
      { lng: end[0], lat: end[1], chainageKm: segmentKm }
    ]

    samples.forEach(sample => {
      const chainageKm = Math.round((segmentStartKm + sample.chainageKm) * 10) / 10
      const atStart = sample.chainageKm <= 0
      const atEnd = sample.chainageKm >= segmentKm
      const stationName = atStart || (!atEnd && sample.chainageKm <= segmentKm / 2) ? fromName : toName
      for (const direction of ['up', 'down'] as const) {
        result.push({
          lng: Math.round(sample.lng * 10000) / 10000,
          lat: Math.round(sample.lat * 10000) / 10000,
          fromStation: fromName,
          toStation: toName,
          stationName,
          direction,
          chainageKm,
          carbonIntensity: mockCarbonIntensity(chainageKm, direction),
          energyIntensity: mockEnergyIntensity(chainageKm, direction)
        })
      }
    })
  }
  return result
}
