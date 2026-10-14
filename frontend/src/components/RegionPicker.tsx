import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Preset, Region } from "../api/types";
import { describeRegion } from "../lib/format";
import type { PickMode } from "./RegionMap";

interface Props {
  region: Region | null;
  onChange: (r: Region) => void;
  mode: PickMode;
  onModeChange: (m: PickMode) => void;
  presets: Preset[];
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export default function RegionPicker({ region, onChange, onModeChange, presets }: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const q = useDebounced(query.trim(), 350);

  const search = useQuery({
    queryKey: ["geocode", q.toLowerCase()],
    queryFn: ({ signal }) => api.geocode(q, signal),
    enabled: q.length >= 2,
    staleTime: 60 * 60 * 1000,
  });


  const showPresets = open && q.length < 2 && presets.length > 0;
  const showResults = open && q.length >= 2;

  return (
    <div className="region-picker">
      <div className="field">
        <label htmlFor="place-search">Search a city, village, or region</label>
        <div className="combo">
          <input
            id="place-search"
            type="search"
            autoComplete="off"
            maxLength={80}
            placeholder="e.g. Ahmedabad, hyderabad, Phoenix…"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 150)}
            aria-expanded={open}
            aria-controls="place-results"
          />
          {(showPresets || showResults) && (
            <ul id="place-results" className="combo-list" role="listbox">
              {showPresets && (
                <>
                  <li className="combo-empty">Quick presets</li>
                  {presets.map((p) => (
                    <li key={p.id}>
                      <button
                        type="button"
                        role="option"
                        aria-selected={false}
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => {
                          const { id: _id, ...rest } = p;
                          onChange(rest as Region);
                          onModeChange(p.kind);
                          setQuery(p.name);
                          setOpen(false);
                        }}
                      >
                        <span>{p.name}</span>
                        <small>{p.kind === "bbox" ? "Region" : "City"}</small>
                      </button>
                    </li>
                  ))}
                </>
              )}
              {showResults && search.isFetching && <li className="combo-empty">Searching…</li>}
              {showResults && search.isError && <li className="combo-empty">Search unavailable right now</li>}
              {showResults && search.data?.length === 0 && <li className="combo-empty">No places found — try clicking on the map</li>}
              {showResults &&
                search.data?.map((r) => (
                  <li key={`${r.lat},${r.lon},${r.name}`}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={false}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => {
                        const name = [r.name, r.admin1, r.country].filter(Boolean).join(", ");
                        onChange({ kind: "point", lat: r.lat, lon: r.lon, name });
                        onModeChange("point");
                        setQuery(name);
                        setOpen(false);
                      }}
                    >
                      <span>{r.name}</span>
                      <small>{[r.admin1, r.country].filter(Boolean).join(", ")}</small>
                    </button>
                  </li>
                ))}
            </ul>
          )}
        </div>
      </div>

      <div className="field">
        <span className="label">Or click a point on the map</span>
      </div>


      {region && (
        <p className="selected-region">
          <strong>{region.name || (region.kind === "point" ? "Custom point" : "Custom box")}</strong>
          <span>{describeRegion(region)}</span>
        </p>
      )}
    </div>
  );
}
