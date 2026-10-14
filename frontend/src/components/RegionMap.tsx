import "leaflet/dist/leaflet.css";
import { useEffect, useState } from "react";
import { CircleMarker, MapContainer, Rectangle, TileLayer, Tooltip, useMap, useMapEvents } from "react-leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import type { Region } from "../api/types";

export type PickMode = "point" | "bbox";

interface Props {
  region: Region | null;
  mode: PickMode;
  onChange: (region: Region) => void;
  gridPoints?: { lat: number; lon: number }[];
}

const round = (v: number) => Math.round(v * 1000) / 1000;
const wrapLon = (lon: number) => ((((lon + 180) % 360) + 360) % 360) - 180;

function ClickHandler({ mode, onChange }: { mode: PickMode; onChange: (r: Region) => void }) {
  const [corner, setCorner] = useState<{ lat: number; lon: number } | null>(null);

  useEffect(() => setCorner(null), [mode]);

  useMapEvents({
    click(e) {
      const lat = round(e.latlng.lat);
      const lon = round(wrapLon(e.latlng.lng));
      if (mode === "point") {
        onChange({ kind: "point", lat, lon, name: null });
        return;
      }
      if (!corner) {
        setCorner({ lat, lon });
        return;
      }
      onChange({
        kind: "bbox",
        south: Math.min(corner.lat, lat),
        north: Math.max(corner.lat, lat),
        west: Math.min(corner.lon, lon),
        east: Math.max(corner.lon, lon),
        name: null,
      });
      setCorner(null);
    },
  });

  return corner ? (
    <CircleMarker center={[corner.lat, corner.lon]} radius={6} pathOptions={{ className: "map-corner" }}>
      <Tooltip permanent direction="top" offset={[0, -6]}>
        Click the opposite corner
      </Tooltip>
    </CircleMarker>
  ) : null;
}

/** Re-centres the map whenever the region changes (e.g. after a search). */
function FitRegion({ region }: { region: Region | null }) {
  const map = useMap();
  const key = region ? JSON.stringify(region) : "";
  useEffect(() => {
    if (!region) return;
    if (region.kind === "point") {
      map.flyTo([region.lat, region.lon], Math.max(map.getZoom(), 7), { duration: 0.6 });
    } else {
      map.flyToBounds(
        [
          [region.south, region.west],
          [region.north, region.east],
        ],
        { padding: [30, 30], duration: 0.6, maxZoom: 9 },
      );
    }
  }, [key]);
  return null;
}

export default function RegionMap({ region, mode, onChange, gridPoints }: Props) {
  const bounds: LatLngBoundsExpression | null =
    region?.kind === "bbox"
      ? [
          [region.south, region.west],
          [region.north, region.east],
        ]
      : null;

  return (
    <div className="map-wrap">
      <MapContainer center={[22.5, 78.9]} zoom={4} minZoom={2} worldCopyJump className="map" aria-label="Region map">
        {/* Standard OSM tiles: no API key needed (light use, attribution required). Dark mode darkens them via CSS. */}
        <TileLayer
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          maxZoom={18}
        />
        <ClickHandler mode={mode} onChange={onChange} />
        <FitRegion region={region} />
        {region?.kind === "point" && (
          <CircleMarker center={[region.lat, region.lon]} radius={8} pathOptions={{ className: "map-point" }} />
        )}
        {bounds && <Rectangle bounds={bounds} pathOptions={{ className: "map-box" }} />}
        {gridPoints?.map((p) => (
          <CircleMarker key={`${p.lat},${p.lon}`} center={[p.lat, p.lon]} radius={4} pathOptions={{ className: "map-grid" }}>
            <Tooltip>
              ERA5 grid cell {p.lat.toFixed(2)}, {p.lon.toFixed(2)}
            </Tooltip>
          </CircleMarker>
        ))}
      </MapContainer>
      <p className="map-hint">
        {mode === "point" ? "Click anywhere on the map to pick a location." : "Click two opposite corners to draw a box (max 5° per side)."}
      </p>
    </div>
  );
}
