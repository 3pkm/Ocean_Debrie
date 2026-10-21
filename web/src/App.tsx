import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import maplibregl, { type GeoJSONSource, type Map as MapLibreMap } from 'maplibre-gl'
import {
  Activity, AlertTriangle, Anchor, ArrowDownRight, ArrowUpRight, CalendarClock, Check,
  ChevronRight, CircleHelp, Clock3, Cloud, Crosshair, ExternalLink, Layers3, LoaderCircle,
  MapPin, Play, Plus, Radio, RefreshCw, Satellite, ShieldAlert, Waves, X,
} from 'lucide-react'
import {
  apiRequest, collectionFrom, featureCollection, type Forecast, type Freshness, type Patch,
  type PatchDetail, type Verification, type VerificationRecord, type Zone,
} from './api'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import 'maplibre-gl/dist/maplibre-gl.css'
import './App.css'

type Feature = ReturnType<typeof featureCollection>['features'][number]
type ReplayStep = 0 | 1 | 2
type ZoneInput = { name: string; advisory: string; warning: string; chatId: string; email: string; webhook: string; secret: string; apiKey: string }

const replayLocation: [number, number] = [-61.22, 13.14]
const ndciTileUrl = import.meta.env.VITE_NDCI_TILE_URL
const fixturePatch = (id: string, status: Patch['status'], coords: [number, number][]): Patch => ({
  patch_id: id,
  status,
  first_seen: '2026-10-14T10:30:00Z',
  last_seen: status === 'occluded' ? '2026-10-19T10:30:00Z' : '2026-10-21T10:30:00Z',
  latest_obs: {
    centroid: { type: 'Point', coordinates: coords[0] },
    geom: { type: 'Polygon', coordinates: [[...coords, coords[0]]] },
    area_m2: 15400,
    confidence: 0.89,
  },
})

function replayPatches(step: ReplayStep): Patch[] {
  if (step === 0) return [fixturePatch('DEMO-0001', 'active', [[-61.22, 13.14], [-61.2, 13.14], [-61.2, 13.16], [-61.22, 13.16]])]
  if (step === 1) return [
    fixturePatch('DEMO-0001-A', 'occluded', [[-61.18, 13.15], [-61.16, 13.15], [-61.16, 13.17], [-61.18, 13.17]]),
    fixturePatch('DEMO-0001-B', 'active', [[-61.24, 13.12], [-61.22, 13.12], [-61.22, 13.14], [-61.24, 13.14]]),
  ]
  return [
    fixturePatch('DEMO-0001-A', 'active', [[-61.11, 13.12], [-61.09, 13.12], [-61.09, 13.14], [-61.11, 13.14]]),
    fixturePatch('DEMO-0001-B', 'active', [[-61.2, 13.08], [-61.18, 13.08], [-61.18, 13.1], [-61.2, 13.1]]),
  ]
}

function replayForecast(step: ReplayStep): Forecast {
  const center: [number, number] = step === 0 ? [-61.21, 13.15] : step === 1 ? [-61.2, 13.145] : [-61.15, 13.12]
  const polygon = (radius: number) => ({
    type: 'Polygon' as const,
    coordinates: [[
      [center[0] - radius, center[1] - radius * 0.65],
      [center[0] + radius, center[1] - radius * 0.65],
      [center[0] + radius, center[1] + radius * 0.65],
      [center[0] - radius, center[1] + radius * 0.65],
      [center[0] - radius, center[1] - radius * 0.65],
    ]],
  })
  return {
    p50: polygon(0.025),
    p90: polygon(0.05),
    centroid: { type: 'Point', coordinates: center },
  }
}

const replayZone: Zone = {
  id: 'demo-zone',
  zone_id: -1,
  name: 'Kingstown Harbour · demo',
  threshold_advisory: 0.2,
  threshold_warning: 0.5,
  geom: { type: 'Polygon', coordinates: [[[-61.23, 13.13], [-61.18, 13.13], [-61.18, 13.17], [-61.23, 13.17], [-61.23, 13.13]]] },
}

const stepNames = ['Day 0 · Patch born', 'Day 5 · Cloud & split', 'Day 7 · Zone alert']
const formatPercent = (value?: number) => value === undefined ? '—' : `${Math.round(value)}%`
const formatAge = (value?: number) => value === undefined ? 'Unknown' : `${value.toFixed(1)}h ago`
const zoneThresholdPercent = (fraction?: number, percent?: number) =>
  `${Math.round(percent ?? (fraction ?? 0.2) * 100)}%`
const recordLabel = (record: { event?: string; type?: string; description?: string; details?: string }) =>
  record.description ?? record.event ?? record.type ?? record.details ?? 'Patch update'

function patchGeometry(patch: Patch) {
  return patch.latest_obs?.geom ?? patch.geom ?? patch.latest_obs?.centroid ?? patch.centroid ?? null
}

function getPolygonCoordinates(coords: Array<[number, number]>) {
  const closed = coords.length && coords[0][0] === coords[coords.length - 1][0] && coords[0][1] === coords[coords.length - 1][1]
    ? coords
    : [...coords, coords[0]]
  return { type: 'Polygon' as const, coordinates: [closed] }
}

function MapPanel({
  patches, zones, forecast, selectedId, horizon, showP50, showP90, showZones, showNdci, drawing,
  draftCoords, onSelectPatch, onMapCoordinate, onDraftComplete,
}: {
  patches: Patch[]; zones: Zone[]; forecast: Forecast | null; selectedId: string | null; horizon: number
  showP50: boolean; showP90: boolean; showZones: boolean; showNdci: boolean; drawing: boolean; draftCoords: [number, number][]
  onSelectPatch: (id: string) => void; onMapCoordinate: (coordinate: [number, number]) => void
  onDraftComplete: () => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const [mapReady, setMapReady] = useState(false)
  const [mapError, setMapError] = useState('')
  const handlersRef = useRef({ onSelectPatch, onMapCoordinate, onDraftComplete, drawing })
  handlersRef.current = { onSelectPatch, onMapCoordinate, onDraftComplete, drawing }

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
      center: replayLocation,
      zoom: 7.2,
      attributionControl: false,
    })
    mapRef.current = map
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right')
    map.on('error', (event) => {
      if (!mapReady) setMapError(event.error?.message ?? 'The map style or tiles could not be loaded.')
    })
    map.on('load', () => {
      map.addSource('patches', { type: 'geojson', data: featureCollection([]) })
      map.addSource('lineage', { type: 'geojson', data: featureCollection([]) })
      map.addSource('zones', { type: 'geojson', data: featureCollection([]) })
      map.addSource('forecast-p50', { type: 'geojson', data: featureCollection([]) })
      map.addSource('forecast-p90', { type: 'geojson', data: featureCollection([]) })
      map.addSource('draft-zone', { type: 'geojson', data: featureCollection([]) })
      if (ndciTileUrl) {
        map.addSource('ndci', {
          type: 'raster',
          tiles: [ndciTileUrl],
          tileSize: 256,
          attribution: 'Indicative NDCI',
        })
      }
      map.addLayer({ id: 'zone-fill', type: 'fill', source: 'zones', paint: { 'fill-color': ['case', ['==', ['get', 'risk_tier'], 'warning'], '#f04438', '#f79009'], 'fill-opacity': 0.16 } })
      if (ndciTileUrl) {
        map.addLayer({ id: 'ndci-layer', type: 'raster', source: 'ndci', paint: { 'raster-opacity': 0.42 } }, 'zone-fill')
      }
      map.addLayer({ id: 'zone-outline', type: 'line', source: 'zones', paint: { 'line-color': '#f79009', 'line-width': 1.5, 'line-opacity': 0.9 } })
      map.addLayer({ id: 'zone-label', type: 'symbol', source: 'zones', layout: { 'text-field': ['get', 'name'], 'text-size': 11, 'text-offset': [0, 1.2], 'text-anchor': 'top', 'text-allow-overlap': true }, paint: { 'text-color': '#f8c66b', 'text-halo-color': '#121719', 'text-halo-width': 1.4 } })
      map.addLayer({ id: 'forecast-p90-fill', type: 'fill', source: 'forecast-p90', paint: { 'fill-color': '#0e7490', 'fill-opacity': 0.25 } })
      map.addLayer({ id: 'forecast-p90-line', type: 'line', source: 'forecast-p90', paint: { 'line-color': '#22d3ee', 'line-width': 1, 'line-opacity': 0.75 } })
      map.addLayer({ id: 'forecast-p50-fill', type: 'fill', source: 'forecast-p50', paint: { 'fill-color': '#087e9c', 'fill-opacity': 0.53 } })
      map.addLayer({ id: 'forecast-p50-line', type: 'line', source: 'forecast-p50', paint: { 'line-color': '#68e6f5', 'line-width': 1.4 } })
      map.addLayer({ id: 'lineage-link', type: 'line', source: 'lineage', paint: { 'line-color': '#72dbe6', 'line-width': 1.2, 'line-opacity': 0.7, 'line-dasharray': [1.5, 2] } })
      map.addLayer({ id: 'lineage-direction', type: 'symbol', source: 'lineage', layout: { 'symbol-placement': 'line', 'text-field': '›', 'text-size': 14, 'text-allow-overlap': true, 'text-rotation-alignment': 'map' }, paint: { 'text-color': '#9eeaf0', 'text-halo-color': '#0c171b', 'text-halo-width': 1 } })
      map.addLayer({ id: 'patch-fill', type: 'fill', source: 'patches', filter: ['in', ['geometry-type'], ['literal', ['Polygon', 'MultiPolygon']]], paint: { 'fill-color': ['match', ['get', 'status'], 'active', '#06b6d4', 'occluded', '#fbbf24', 'stranded', '#f97316', 'lost', '#a1a1aa', '#60a5fa'], 'fill-opacity': ['case', ['==', ['get', 'status'], 'lost'], 0.16, 0.48] } })
      map.addLayer({ id: 'patch-outline', type: 'line', source: 'patches', filter: ['in', ['geometry-type'], ['literal', ['Polygon', 'MultiPolygon']]], paint: { 'line-color': ['match', ['get', 'status'], 'active', '#22d3ee', 'occluded', '#fbbf24', 'stranded', '#fb923c', 'lost', '#9ca3af', '#60a5fa'], 'line-width': ['case', ['==', ['get', 'patch_id'], selectedId ?? ''], 2.6, 1.2], 'line-dasharray': ['case', ['==', ['get', 'status'], 'occluded'], ['literal', [2, 2]], ['literal', [1, 0]]] } })
      map.addLayer({ id: 'patch-points', type: 'circle', source: 'patches', filter: ['==', ['geometry-type'], 'Point'], paint: { 'circle-radius': ['case', ['==', ['get', 'patch_id'], selectedId ?? ''], 8, 6], 'circle-color': ['match', ['get', 'status'], 'active', '#22d3ee', 'occluded', '#fbbf24', 'stranded', '#fb923c', 'lost', '#a1a1aa', '#60a5fa'], 'circle-stroke-color': '#e6fdff', 'circle-stroke-width': 1.4, 'circle-opacity': ['case', ['==', ['get', 'status'], 'lost'], 0.45, 0.95] } })
      map.addLayer({ id: 'patch-label', type: 'symbol', source: 'patches', layout: { 'text-field': ['get', 'patch_id'], 'text-size': 10, 'text-offset': [0, 1.5], 'text-allow-overlap': true }, paint: { 'text-color': '#e6fdff', 'text-halo-color': '#061114', 'text-halo-width': 1.4 } })
      map.addLayer({ id: 'draft-fill', type: 'fill', source: 'draft-zone', paint: { 'fill-color': '#34d399', 'fill-opacity': 0.18 } })
      map.addLayer({ id: 'draft-line', type: 'line', source: 'draft-zone', paint: { 'line-color': '#34d399', 'line-width': 2, 'line-dasharray': [2, 2] } })
      map.addLayer({ id: 'draft-points', type: 'circle', source: 'draft-zone', filter: ['==', ['geometry-type'], 'Point'], paint: { 'circle-radius': 5, 'circle-color': '#34d399', 'circle-stroke-color': '#fff', 'circle-stroke-width': 1 } })
      setMapReady(true)
    })
    map.on('click', (event) => {
      const state = handlersRef.current
      if (state.drawing) {
        state.onMapCoordinate([event.lngLat.lng, event.lngLat.lat])
        return
      }
      const features = map.queryRenderedFeatures(event.point, { layers: ['patch-fill', 'patch-outline', 'patch-points'] })
      const patchId = features[0]?.properties?.patch_id
      if (typeof patchId === 'string') state.onSelectPatch(patchId)
    })
    map.on('mouseenter', 'patch-fill', () => { map.getCanvas().style.cursor = 'pointer' })
    map.on('mouseleave', 'patch-fill', () => { map.getCanvas().style.cursor = handlersRef.current.drawing ? 'crosshair' : '' })
    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  const patchFeatures = useMemo(() => patches.flatMap((patch) => {
    const geometry = patchGeometry(patch)
    return geometry ? [{ type: 'Feature' as const, id: patch.patch_id, geometry, properties: { patch_id: patch.patch_id, status: patch.status, selected: patch.patch_id === selectedId } }] : []
  }), [patches, selectedId])
  const zoneFeatures = useMemo(() => zones.flatMap((zone) => {
    const geometry = zone.geom ?? zone.geometry
    return geometry ? [{ type: 'Feature' as const, geometry, properties: { name: zone.name, zone_id: zone.zone_id ?? zone.id ?? zone.name, risk_tier: zone.risk_tier ?? zone.alert_tier ?? 'advisory', advisory_threshold: zone.threshold_advisory ?? (zone.advisory_threshold ?? 20) / 100, warning_threshold: zone.threshold_warning ?? (zone.warning_threshold ?? 50) / 100 } }] : []
  }), [zones])
  const lineageFeatures = useMemo(() => patches.flatMap((child) => {
    if (!child.parent_id) return []
    const parent = patches.find((patch) => patch.patch_id === child.parent_id)
    const parentPoint = parent?.latest_obs?.centroid?.coordinates ?? parent?.centroid?.coordinates
    const childPoint = child.latest_obs?.centroid?.coordinates ?? child.centroid?.coordinates
    return parentPoint && childPoint ? [{
      type: 'Feature' as const,
      geometry: { type: 'LineString' as const, coordinates: [parentPoint, childPoint] },
      properties: { parent_id: child.parent_id, child_id: child.patch_id },
    }] : []
  }), [patches])
  const draftFeature = useMemo(() => {
    const features: Feature[] = []
    if (draftCoords.length > 0) {
      features.push({ type: 'Feature', geometry: { type: 'MultiPoint', coordinates: draftCoords }, properties: {} } as Feature)
      if (draftCoords.length >= 3) features.push({ type: 'Feature', geometry: getPolygonCoordinates(draftCoords), properties: {} } as Feature)
    }
    return featureCollection(features)
  }, [draftCoords])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    const update = (id: string, data: ReturnType<typeof featureCollection>) => {
      const source = map.getSource(id) as GeoJSONSource | undefined
      source?.setData(data)
    }
    update('patches', featureCollection(patchFeatures))
    update('lineage', featureCollection(lineageFeatures))
    update('zones', featureCollection(zoneFeatures))
    update('forecast-p50', featureCollection(forecast?.p50 ? [{ type: 'Feature', geometry: forecast.p50, properties: {} }] as Feature[] : []))
    update('forecast-p90', featureCollection(forecast?.p90 ? [{ type: 'Feature', geometry: forecast.p90, properties: {} }] as Feature[] : []))
    update('draft-zone', draftFeature)
    map.setLayoutProperty('zone-fill', 'visibility', showZones ? 'visible' : 'none')
    map.setLayoutProperty('zone-outline', 'visibility', showZones ? 'visible' : 'none')
    map.setLayoutProperty('zone-label', 'visibility', showZones ? 'visible' : 'none')
    if (ndciTileUrl && map.getLayer('ndci-layer')) {
      map.setLayoutProperty('ndci-layer', 'visibility', showNdci ? 'visible' : 'none')
    }
    for (const id of ['forecast-p50-fill', 'forecast-p50-line']) map.setLayoutProperty(id, 'visibility', showP50 ? 'visible' : 'none')
    for (const id of ['forecast-p90-fill', 'forecast-p90-line']) map.setLayoutProperty(id, 'visibility', showP90 ? 'visible' : 'none')
    for (const id of ['draft-fill', 'draft-line', 'draft-points']) map.setLayoutProperty(id, 'visibility', drawing ? 'visible' : 'none')
    map.getCanvas().style.cursor = drawing ? 'crosshair' : ''
    const selected = patches.find((patch) => patch.patch_id === selectedId)
    const center = selected?.latest_obs?.centroid?.coordinates ?? selected?.centroid?.coordinates
    if (center) map.easeTo({ center, duration: 450 })
  }, [draftFeature, drawing, forecast, horizon, lineageFeatures, mapReady, patchFeatures, patches, selectedId, showNdci, showP50, showP90, showZones, zoneFeatures])

  return <div className="map-wrap"><div ref={containerRef} className="map-canvas" />
    {!mapReady && <div className="map-loading">{mapError ? <><AlertTriangle size={17} /> Basemap unavailable · {mapError}</> : <><LoaderCircle size={19} className="spin" /> Loading ocean map…</>}</div>}
    {drawing && <div className="draw-hint"><MapPin size={15} /> Click the map to add zone vertices ({draftCoords.length}/3 minimum) <button disabled={draftCoords.length < 3} onClick={onDraftComplete}>Finish polygon</button></div>}
    <div className="map-legend">
      <span><i className="legend-dot active" />Active</span><span><i className="legend-dot occluded" />Occluded</span>
      <span><i className="legend-dot lost" />Lost</span><span><i className="legend-zone" />Zone</span>
      <span className="legend-note"><span className="legend-p50" /> P50 <span className="legend-p90" /> P90</span>
    </div>
    <div className="map-credit">MapLibre · Carto Dark Matter · Horizon {horizon}h</div>
  </div>
}

function App() {
  const [patches, setPatches] = useState<Patch[]>([])
  const [zones, setZones] = useState<Zone[]>([])
  const [freshness, setFreshness] = useState<Freshness | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [forecast, setForecast] = useState<Forecast | null>(null)
  const [detail, setDetail] = useState<PatchDetail | null>(null)
  const [verification, setVerification] = useState<Verification | null>(null)
  const [horizon, setHorizon] = useState<24 | 48>(24)
  const [showP50, setShowP50] = useState(true)
  const [showP90, setShowP90] = useState(true)
  const [showZones, setShowZones] = useState(true)
  const [showNdci, setShowNdci] = useState(false)
  const [errors, setErrors] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [drawerBusy, setDrawerBusy] = useState(false)
  const [fetchBusy, setFetchBusy] = useState(false)
  const [fetchMessage, setFetchMessage] = useState('')
  const [registerOpen, setRegisterOpen] = useState(false)
  const [zoneInput, setZoneInput] = useState<ZoneInput>({ name: '', advisory: '20', warning: '50', chatId: '', email: '', webhook: '', secret: '', apiKey: '' })
  const [drawing, setDrawing] = useState(false)
  const [draftCoords, setDraftCoords] = useState<[number, number][]>([])
  const [replayEnabled, setReplayEnabled] = useState(false)
  const [replayStep, setReplayStep] = useState<ReplayStep>(0)
  const [replayNotice, setReplayNotice] = useState('')

  const refresh = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true)
    setErrors([])
    const [patchResponse, zoneResponse, freshnessResponse] = await Promise.allSettled([
      apiRequest<unknown>('/api/patches'),
      apiRequest<unknown>('/api/zones'),
      apiRequest<Freshness>('/api/freshness'),
    ])
    const nextErrors: string[] = []
    if (patchResponse.status === 'fulfilled') setPatches(collectionFrom<Patch>(patchResponse.value, 'patches'))
    else nextErrors.push(`Patches: ${patchResponse.reason instanceof Error ? patchResponse.reason.message : 'Unable to load patches'}`)
    if (zoneResponse.status === 'fulfilled') setZones(collectionFrom<Zone>(zoneResponse.value, 'zones'))
    else nextErrors.push(`Zones: ${zoneResponse.reason instanceof Error ? zoneResponse.reason.message : 'Unable to load zones'}`)
    if (freshnessResponse.status === 'fulfilled') setFreshness(freshnessResponse.value)
    else nextErrors.push(`Freshness: ${freshnessResponse.reason instanceof Error ? freshnessResponse.reason.message : 'Unable to load freshness'}`)
    setErrors(nextErrors)
    setLoading(false)
  }, [])

  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    const timer = window.setInterval(() => { void refresh(true) }, 30_000)
    return () => window.clearInterval(timer)
  }, [refresh])
  const displayedPatches = replayEnabled ? replayPatches(replayStep) : patches
  const displayedZones = replayEnabled && replayStep === 2 ? [...zones, replayZone] : zones
  const displayedForecast = replayEnabled ? replayForecast(replayStep) : forecast
  const activeCount = displayedPatches.filter((patch) => patch.status === 'active').length
  const occludedCount = displayedPatches.filter((patch) => patch.status === 'occluded').length
  const selectedPatch = displayedPatches.find((patch) => patch.patch_id === selectedId) ?? null

  useEffect(() => {
    if (!selectedId || replayEnabled) {
      setForecast(null)
      setVerification(null)
      setDetail(null)
      return
    }
    let cancelled = false
    setForecast(null)
    setVerification(null)
    setDetail(null)
    setDrawerBusy(true)
    const encodedId = encodeURIComponent(selectedId)
    Promise.allSettled([
      apiRequest<Forecast>(`/api/forecasts/${encodedId}?horizon=${horizon}`),
      apiRequest<Verification>(`/api/verifications?patch=${encodedId}`),
      apiRequest<PatchDetail>(`/api/patches/${encodedId}`),
    ]).then((results) => {
      if (cancelled) return
      const nextErrors: string[] = []
      if (results[0].status === 'fulfilled') setForecast(results[0].value)
      else nextErrors.push(`Forecast unavailable: ${results[0].reason instanceof Error ? results[0].reason.message : 'request failed'}`)
      if (results[1].status === 'fulfilled') setVerification(results[1].value)
      else nextErrors.push(`Verification analytics unavailable: ${results[1].reason instanceof Error ? results[1].reason.message : 'request failed'}`)
      if (results[2].status === 'fulfilled') setDetail(results[2].value)
      else nextErrors.push(`Patch timeline unavailable: ${results[2].reason instanceof Error ? results[2].reason.message : 'request failed'}`)
      if (nextErrors.length) setErrors((old) => [...old.filter((error) => !error.startsWith('Forecast unavailable') && !error.startsWith('Verification analytics unavailable') && !error.startsWith('Patch timeline unavailable')), ...nextErrors])
      setDrawerBusy(false)
    })
    return () => { cancelled = true }
  }, [horizon, replayEnabled, selectedId])

  const onMapCoordinate = useCallback((coordinate: [number, number]) => setDraftCoords((coords) => [...coords, coordinate]), [])
  const onDraftComplete = useCallback(() => setDrawing(false), [])

  const handleFetchLatest = async () => {
    setFetchBusy(true)
    setFetchMessage('')
    try {
      const response = await apiRequest<{ status?: string; job_id?: string; message?: string }>('/api/jobs/fetch_latest', { method: 'POST', body: JSON.stringify({}) })
      setFetchMessage(response.message ?? `Fetch job ${response.job_id ? `#${response.job_id} ` : ''}${response.status ?? 'queued'}.`)
      window.setTimeout(() => { void refresh(true) }, 3000)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Request failed'
      setFetchMessage(`Unable to fetch latest: ${message}`)
      setErrors((old) => [...old.filter((item) => !item.startsWith('Fetch latest:')), `Fetch latest: ${message}`])
    } finally {
      setFetchBusy(false)
    }
  }

  const submitZone = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (draftCoords.length < 3) {
      setErrors((old) => [...old.filter((item) => !item.startsWith('Zone registration:')), 'Zone registration: Draw a polygon with at least three map points.'])
      return
    }
    try {
      const registered = await apiRequest<Zone>('/api/zones', {
        method: 'POST',
        headers: { Authorization: `Bearer ${zoneInput.apiKey}` },
        body: JSON.stringify({
          name: zoneInput.name,
          geom: getPolygonCoordinates(draftCoords),
          threshold_advisory: Number(zoneInput.advisory) / 100,
          threshold_warning: Number(zoneInput.warning) / 100,
          channels: { telegram_chat_id: zoneInput.chatId || undefined, email: zoneInput.email || undefined, webhook_url: zoneInput.webhook || undefined, webhook_secret: zoneInput.secret || undefined },
        }),
      })
      setZones((old) => [...old, registered])
      setErrors((old) => old.filter((item) => !item.startsWith('Zone registration:')))
      setRegisterOpen(false)
      setDrawing(false)
      setDraftCoords([])
      setZoneInput({ name: '', advisory: '20', warning: '50', chatId: '', email: '', webhook: '', secret: '', apiKey: '' })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Request failed'
      setErrors((old) => [...old.filter((item) => !item.startsWith('Zone registration:')), `Zone registration: ${message}`])
    }
  }

  const selectPatch = (id: string) => {
    setSelectedId(id)
    if (replayEnabled) return
  }
  const replay = (step: ReplayStep) => {
    setReplayStep(step)
    const first = replayPatches(step)[0]
    setSelectedId(first.patch_id)
    setReplayNotice(step === 2 ? 'Demo alert: drift forecast intersects the Kingstown Harbour warning zone.' : '')
  }
  const timeline = detail?.timeline ?? detail?.events ?? []
  const records: VerificationRecord[] = verification?.records ?? []
  const verificationSummary = verification?.summary

  return <main className="app-shell">
    <header className="topbar">
      <a className="brand" href="#" aria-label="Tidewatch home"><span className="brand-mark"><Waves size={17} /></span><span>TIDEWATCH</span><span className="brand-divider" /> <span className="brand-subtitle">MARINE DEBRIS INTELLIGENCE</span></a>
      <div className="top-actions"><span className="live-pill"><i /> Live monitoring</span><button className="icon-button" aria-label="Help"><CircleHelp size={17} /></button><div className="avatar">TW</div></div>
    </header>
    <section className="freshness-bar" aria-label="Data freshness">
      <div className="freshness-lead"><span className="status-led" /><span>System status <strong>{freshness ? 'Nominal' : 'Connecting'}</strong></span></div>
      <div className="freshness-item"><Satellite size={14} /><span>Sentinel-2 <b>{formatAge(freshness?.last_scene_age_hours)}</b></span></div>
      <div className="freshness-item"><Cloud size={14} /><span>GFS wind <b>{freshness?.wind_forecast_updated_utc ? `${new Date(freshness.wind_forecast_updated_utc).toISOString().slice(11, 16)}Z` : '—'}</b></span></div>
      <div className="freshness-item"><Waves size={14} /><span>Currents <b>{freshness?.currents_forecast_updated_utc ? `${new Date(freshness.currents_forecast_updated_utc).toISOString().slice(11, 16)}Z` : '—'}</b></span></div>
      <div className="freshness-item"><Activity size={14} /><span>Risk engine <b>{freshness?.last_risk_refresh_utc ? 'Nominal' : 'Unknown'}</b></span></div>
      <div className="freshness-update">{freshness?.last_scene_utc ? `Updated ${new Date(freshness.last_scene_utc).toLocaleString()}` : 'Waiting for telemetry'}</div>
    </section>

    {errors.length > 0 && <section className="error-stack" role="alert" aria-live="polite">{errors.map((error, index) => <div className="error-message" key={`${index}-${error}`}><AlertTriangle size={15} /><span>{error}</span><button aria-label="Dismiss error" onClick={() => setErrors((old) => old.filter((_, itemIndex) => itemIndex !== index))}><X size={14} /></button></div>)}</section>}

    <section className="page-heading">
      <div><div className="eyebrow"><span>OPERATIONAL OVERVIEW</span><span className="eyebrow-dot" /> EASTERN CARIBBEAN</div><h1>Drift intelligence</h1><p>Track floating debris, forecast drift and protect coastal zones.</p></div>
      <div className="heading-actions">
        <button className={`button button-secondary ${replayEnabled ? 'replay-active' : ''}`} onClick={() => {
          const enabled = !replayEnabled
          setReplayEnabled(enabled)
          setReplayNotice('')
          if (enabled) replay(0)
          else { setSelectedId(null); void refresh(true) }
        }}><Play size={15} /> {replayEnabled ? 'Exit replay' : 'Replay mode'}</button>
        <button className="button button-primary" onClick={() => void handleFetchLatest()} disabled={fetchBusy}><RefreshCw size={15} className={fetchBusy ? 'spin' : ''} /> {fetchBusy ? 'Queuing…' : 'Fetch latest'}</button>
      </div>
    </section>

    {replayEnabled && <section className="replay-banner">
      <div className="replay-title"><span className="replay-icon"><Play size={14} fill="currentColor" /></span><div><strong>Replay mode · local visual demo</strong><small>Illustrative data only. This preview does not write to the API.</small></div></div>
      <div className="replay-steps">{stepNames.map((name, index) => <button key={name} className={replayStep === index ? 'selected' : ''} onClick={() => replay(index as ReplayStep)}><span>{index + 1}</span>{name}</button>)}</div>
    </section>}
    {replayNotice && <div className="replay-alert"><ShieldAlert size={16} /><span>{replayNotice}</span><button onClick={() => setReplayNotice('')} aria-label="Dismiss replay alert"><X size={14} /></button></div>}
    {fetchMessage && <div className="action-message"><Check size={15} />{fetchMessage}<button aria-label="Dismiss message" onClick={() => setFetchMessage('')}><X size={14} /></button></div>}

    <section className="metrics-grid">
      <Metric icon={<Layers3 size={17} />} label="Tracked patches" value={loading && !replayEnabled ? '…' : displayedPatches.length} note={`${activeCount} active · ${occludedCount} occluded`} accent="cyan" />
      <Metric icon={<ShieldAlert size={17} />} label="Zones protected" value={displayedZones.length} note={`${freshness?.pending_alerts_count ?? 0} pending alerts`} accent="orange" />
      <Metric icon={<Crosshair size={17} />} label="Hit rate · P50" value={formatPercent(verificationSummary?.in_p50_pct)} note="Ideal calibration · 50%" accent="blue" />
      <Metric icon={<Radio size={17} />} label="Hit rate · P90" value={formatPercent(verificationSummary?.in_p90_pct)} note="Ideal calibration · 90%" accent="purple" />
    </section>

    <section className="content-grid">
      <div className="map-card">
        <div className="card-heading map-heading"><div><div className="section-label"><MapPin size={13} /> GEOSPATIAL VIEW</div><h2>Patch & zone map</h2></div>
          <div className="map-tools">
            <div className="segmented" aria-label="Forecast horizon">{([24, 48] as const).map((value) => <button className={horizon === value ? 'active' : ''} key={value} onClick={() => setHorizon(value)}>{value}h</button>)}</div>
            <label className="layer-control"><input type="checkbox" checked={showP50} onChange={(event) => setShowP50(event.target.checked)} />P50</label>
            <label className="layer-control"><input type="checkbox" checked={showP90} onChange={(event) => setShowP90(event.target.checked)} />P90</label>
            <label className="layer-control"><input type="checkbox" checked={showZones} onChange={(event) => setShowZones(event.target.checked)} />Zones</label>
            <label className="layer-control" title={ndciTileUrl ? 'Indicative NDCI raster overlay' : 'Set VITE_NDCI_TILE_URL to enable the NDCI raster overlay'}><input type="checkbox" checked={showNdci} disabled={!ndciTileUrl} onChange={(event) => setShowNdci(event.target.checked)} />Indicative NDCI</label>
            <button className="button button-small" onClick={() => { setRegisterOpen(true); setDraftCoords([]); setDrawing(true) }}><Plus size={14} /> Register zone</button>
          </div>
        </div>
        <MapPanel patches={displayedPatches} zones={displayedZones} forecast={displayedForecast} selectedId={selectedId} horizon={horizon} showP50={showP50} showP90={showP90} showZones={showZones} showNdci={showNdci} drawing={drawing} draftCoords={draftCoords} onSelectPatch={selectPatch} onMapCoordinate={onMapCoordinate} onDraftComplete={onDraftComplete} />
        <div className="map-footnote"><span><i className="legend-p50" /> 50% chance the patch is inside the dark area; 90% inside the outer boundary.</span><span><span className="status-led small" /> {loading && !replayEnabled ? 'Syncing patches…' : `${displayedPatches.length} patches visible`}</span></div>
      </div>

      <aside className="side-column">
        <div className="panel-card patch-panel">
          <div className="card-heading"><div><div className="section-label"><Anchor size={13} /> PATCH TRACKING</div><h2>Tracked patches <span className="heading-count">{displayedPatches.length}</span></h2></div><button className="text-button" onClick={() => void refresh()}><RefreshCw size={13} /> Refresh</button></div>
          <div className="patch-list">
            {displayedPatches.length === 0 ? <EmptyState loading={loading} label="No patches returned by the API." /> : displayedPatches.map((patch) => <button className={`patch-row ${selectedId === patch.patch_id ? 'selected' : ''}`} key={patch.patch_id} onClick={() => selectPatch(patch.patch_id)}>
              <span className={`patch-symbol ${patch.status}`}><i /></span><span className="patch-copy"><strong>{patch.patch_id}</strong><small>{patch.parent_id ? `Child of ${patch.parent_id} · ` : ''}{patch.status === 'occluded' ? 'Not observed · forecast only' : patch.status}</small></span>
              <span className={`status-badge ${patch.status}`}>{patch.status}</span><ChevronRight size={14} className="row-chevron" />
            </button>)}
          </div>
          {selectedPatch && <PatchDrawer patch={selectedPatch} detail={detail} verification={verification} records={records} busy={drawerBusy} onClose={() => setSelectedId(null)} replayEnabled={replayEnabled} />}
        </div>

        <div className="panel-card analytics-panel">
          <div className="card-heading"><div><div className="section-label"><Activity size={13} /> MODEL PERFORMANCE</div><h2>Forecast verification</h2></div><span className="sample-count">{verificationSummary?.total_matched ?? records.length} matched</span></div>
          {records.length > 0 ? <div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><AreaChart data={records} margin={{ top: 9, right: 8, left: -20, bottom: 0 }}>
            <defs><linearGradient id="error-gradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#22d3ee" stopOpacity={0.27} /><stop offset="100%" stopColor="#22d3ee" stopOpacity={0.01} /></linearGradient></defs>
            <CartesianGrid stroke="#29353a" strokeDasharray="3 4" vertical={false} /><XAxis dataKey="lead_h" tickFormatter={(value: number) => `${value}h`} tick={{ fill: '#78878d', fontSize: 10 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: '#78878d', fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip contentStyle={{ background: '#111a1e', border: '1px solid #29353a', borderRadius: 8, color: '#eff7f8', fontSize: 11 }} labelFormatter={(value) => `Lead ${value}h`} formatter={(value, name) => [`${Number(value).toFixed(1)} km`, name]} />
            <Area type="monotone" dataKey="error_km" name="Model" stroke="#22d3ee" strokeWidth={2} fill="url(#error-gradient)" />
            <Area type="monotone" dataKey="persistence_error_km" name="Persistence" stroke="#fbbf24" strokeWidth={1.5} fill="none" />
            <Area type="monotone" dataKey="currents_only_error_km" name="Currents only" stroke="#a78bfa" strokeWidth={1.5} fill="none" />
          </AreaChart></ResponsiveContainer></div> : <EmptyState loading={drawerBusy && !!selectedId} label={selectedId ? 'Verification data is not available for this patch.' : 'Select a patch to load verification results.'} />}
          <div className="chart-legend"><span><i className="line-key model" />Model</span><span><i className="line-key persistence" />Persistence</span><span><i className="line-key currents" />Currents only</span></div>
          <div className="analytics-summary"><span>Mean error <b>{verificationSummary?.mean_error_km !== undefined ? `${verificationSummary.mean_error_km.toFixed(1)} km` : '—'}</b></span><span>P50 <b>{formatPercent(verificationSummary?.in_p50_pct)} <em>· ideal 50%</em></b></span><span>P90 <b>{formatPercent(verificationSummary?.in_p90_pct)} <em>· ideal 90%</em></b></span></div>
        </div>
      </aside>
    </section>

    <section className="bottom-grid">
      <div className="panel-card freshness-card"><div className="section-label"><CalendarClock size={13} /> DATA FRESHNESS</div><h2>Pipeline telemetry</h2><div className="telemetry-grid">
        <Telemetry label="Last satellite scene" value={freshness?.last_scene_utc ? new Date(freshness.last_scene_utc).toLocaleString() : 'Not reported'} icon={<Satellite size={14} />} />
        <Telemetry label="Wind forecast" value={freshness?.wind_forecast_updated_utc ? new Date(freshness.wind_forecast_updated_utc).toLocaleString() : 'Not reported'} icon={<Cloud size={14} />} />
        <Telemetry label="Ocean currents" value={freshness?.currents_forecast_updated_utc ? new Date(freshness.currents_forecast_updated_utc).toLocaleString() : 'Not reported'} icon={<Waves size={14} />} />
        <Telemetry label="Risk engine refresh" value={freshness?.last_risk_refresh_utc ? new Date(freshness.last_risk_refresh_utc).toLocaleString() : 'Not reported'} icon={<Activity size={14} />} />
      </div></div>
      <div className="panel-card zones-card"><div className="card-heading"><div><div className="section-label"><ShieldAlert size={13} /> COASTAL PROTECTION</div><h2>Registered zones</h2></div><button className="text-button" onClick={() => { setRegisterOpen(true); setDraftCoords([]); setDrawing(true) }}><Plus size={13} /> Add zone</button></div>
        {displayedZones.length === 0 ? <EmptyState loading={loading} label="No registered zones." /> : <div className="zone-list">{displayedZones.map((zone) => <div className="zone-row" key={zone.zone_id ?? zone.id ?? zone.name}><span className="zone-marker"><MapPin size={15} /></span><div><strong>{zone.name}</strong><small>Advisory {zoneThresholdPercent(zone.threshold_advisory, zone.advisory_threshold)} · Warning {zoneThresholdPercent(zone.threshold_warning, zone.warning_threshold)}</small></div><span className="zone-state">{replayEnabled && zone.id === 'demo-zone' ? 'DEMO ALERT' : 'MONITORING'}</span></div>)}</div>}
      </div>
    </section>
    <footer><span>© 2026 Tidewatch · Marine debris monitoring</span><span>Indicative forecasts · Not a substitute for local maritime advisories</span><a href="https://maplibre.org/" target="_blank" rel="noreferrer"><ExternalLink size={12} /> MapLibre</a></footer>

    {registerOpen && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) { setRegisterOpen(false); setDrawing(false) } }}>
      <section className="zone-modal" role="dialog" aria-modal="true" aria-labelledby="zone-title">
        <div className="modal-header"><div><div className="section-label"><MapPin size={13} /> COASTAL PROTECTION</div><h2 id="zone-title">Register a zone</h2><p>Draw a boundary directly on the map, then set alert thresholds.</p></div><button className="icon-button" onClick={() => { setRegisterOpen(false); setDrawing(false) }} aria-label="Close registration"><X size={18} /></button></div>
        <form onSubmit={(event) => void submitZone(event)}>
          <label className="form-label">Zone name<input required value={zoneInput.name} onChange={(event) => setZoneInput({ ...zoneInput, name: event.target.value })} placeholder="e.g. Kingstown Harbour" /></label>
          <div className="form-row"><label className="form-label">Advisory threshold (%)<input type="number" min="0" max="100" value={zoneInput.advisory} onChange={(event) => setZoneInput({ ...zoneInput, advisory: event.target.value })} /></label><label className="form-label">Warning threshold (%)<input type="number" min="0" max="100" value={zoneInput.warning} onChange={(event) => setZoneInput({ ...zoneInput, warning: event.target.value })} /></label></div>
          <div className="drawing-status"><span className="draw-led" /><div><strong>{drawing ? 'Zone drawing enabled' : 'Boundary ready'}</strong><small>{draftCoords.length} points · Minimum 3. Click points on the map behind this dialog.</small></div><button type="button" className="text-button" onClick={() => { setDraftCoords([]); setDrawing(true) }}><RefreshCw size={12} /> Reset</button></div>
          <div className="form-section-title">Alert channels <span>Optional</span></div>
          <label className="form-label">Telegram chat ID<input value={zoneInput.chatId} onChange={(event) => setZoneInput({ ...zoneInput, chatId: event.target.value })} placeholder="Chat ID" /></label>
          <label className="form-label">Email<input type="email" value={zoneInput.email} onChange={(event) => setZoneInput({ ...zoneInput, email: event.target.value })} placeholder="coast@example.org" /></label>
          <label className="form-label">Webhook URL<input type="url" value={zoneInput.webhook} onChange={(event) => setZoneInput({ ...zoneInput, webhook: event.target.value })} placeholder="https://…" /></label>
          <label className="form-label">Webhook signing secret<input type="password" value={zoneInput.secret} onChange={(event) => setZoneInput({ ...zoneInput, secret: event.target.value })} placeholder="Optional signing secret" /></label>
          <label className="form-label">Authority API key<input required type="password" autoComplete="off" value={zoneInput.apiKey} onChange={(event) => setZoneInput({ ...zoneInput, apiKey: event.target.value })} placeholder="Zone registration API key" /></label>
          <div className="modal-actions"><button type="button" className="button button-secondary" onClick={() => { setRegisterOpen(false); setDrawing(false) }}>Cancel</button><button className="button button-primary" type="submit"><Plus size={14} /> Save zone</button></div>
        </form>
      </section>
    </div>}
  </main>
}

function Metric({ icon, label, value, note, accent }: { icon: React.ReactNode; label: string; value: React.ReactNode; note: string; accent: string }) {
  return <article className={`metric-card ${accent}`}><div className="metric-icon">{icon}</div><div><div className="metric-label">{label}</div><div className="metric-value">{value}</div><div className="metric-note">{note}</div></div><div className="metric-trend">{accent === 'orange' ? <ArrowUpRight size={15} /> : accent === 'purple' ? <ArrowDownRight size={15} /> : <Activity size={15} />}</div></article>
}

function EmptyState({ loading, label }: { loading?: boolean; label: string }) {
  return <div className="empty-state">{loading ? <LoaderCircle size={18} className="spin" /> : <Clock3 size={18} />}<span>{loading ? 'Loading…' : label}</span></div>
}

function Telemetry({ label, value, icon }: { label: string; value: string; icon: React.ReactNode }) {
  return <div className="telemetry-item"><span className="telemetry-icon">{icon}</span><span><small>{label}</small><strong>{value}</strong></span></div>
}

function PatchDrawer({ patch, detail, verification, records, busy, onClose, replayEnabled }: {
  patch: Patch; detail: PatchDetail | null; verification: Verification | null; records: VerificationRecord[]
  busy: boolean; onClose: () => void; replayEnabled: boolean
}) {
  const events = detail?.timeline ?? detail?.events ?? (replayEnabled ? [
    { event: 'Patch born', created_at: '2026-10-14T10:30:00Z' },
    ...(patch.status === 'occluded' || patch.patch_id.endsWith('-A') ? [{ event: 'Cloud cover detected · parent patch split', created_at: '2026-10-19T10:30:00Z' }] : []),
    ...(patch.status === 'active' && patch.patch_id.endsWith('-B') ? [{ event: 'Reacquired by Sentinel-2', created_at: '2026-10-21T10:30:00Z' }] : []),
    ...(patch.status === 'active' && patch.patch_id.endsWith('-A') ? [{ event: 'Drift forecast intersects warning zone', created_at: '2026-10-21T10:30:00Z' }] : []),
  ] : [])
  return <div className="patch-detail">
    <div className="detail-header"><div><span className="section-label"><MapPin size={12} /> PATCH DETAIL</span><strong>{patch.patch_id}</strong></div><button className="icon-button" aria-label="Close patch details" onClick={onClose}><X size={16} /></button></div>
    <div className="detail-stats"><span><small>STATUS</small><b className={`detail-status ${patch.status}`}>{patch.status}</b></span><span><small>AREA</small><b>{patch.latest_obs?.area_m2 ? `${(patch.latest_obs.area_m2 / 10000).toFixed(2)} ha` : '—'}</b></span><span><small>CONFIDENCE</small><b>{patch.latest_obs?.confidence !== undefined ? `${Math.round(patch.latest_obs.confidence * 100)}%` : '—'}</b></span></div>
    {patch.parent_id && <div className="lineage-note"><ChevronRight size={13} /> Fragment lineage · parent {patch.parent_id}</div>}
    <div className="timeline-heading">Lifecycle <span>{events.length} events</span></div>
    {busy ? <EmptyState loading label="" /> : events.length ? <div className="timeline">{events.map((event, index) => <div className="timeline-event" key={`${recordLabel(event)}-${index}`}><span className="timeline-dot" /><div><strong>{recordLabel(event)}</strong><small>{event.created_at ?? event.timestamp ? new Date(event.created_at ?? event.timestamp ?? '').toLocaleString() : 'Time not reported'}</small></div></div>)}</div> : <div className="detail-placeholder">Timeline is not available for this patch.</div>}
    {verification?.summary && <div className="detail-accuracy"><span>Mean forecast error <b>{verification.summary.mean_error_km?.toFixed(1) ?? '—'} km</b></span><span>Matched passes <b>{verification.summary.total_matched ?? records.length}</b></span></div>}
  </div>
}

export default App
